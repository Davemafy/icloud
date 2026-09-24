from __future__ import annotations

from typing import Any

from .models import Analysis, Direction, MarketSnapshot, Zone

TARGET_REVALIDATION_CONTRACT = "TARGET_LADDER_REVALIDATION_V6571"
_M15_SECONDS = 15 * 60


def _note_int(zone: Zone, prefix: str, default: int = 0) -> int:
    for note in list(zone.notes or []):
        text = str(note)
        if not text.startswith(prefix):
            continue
        try:
            return int(float(text.split(":", 1)[1]))
        except (TypeError, ValueError, IndexError):
            return default
    return default


def _target_gap(snapshot: MarketSnapshot) -> float:
    point = max(abs(float(snapshot.point or 0.01)), 1e-9)
    return max(
        point * 5.0,
        point * float(snapshot.spread_points or 0.0) * 1.50,
    )


def _ahead(direction: Direction, target: float, reference: float, gap: float) -> bool:
    if direction == Direction.BUY:
        return float(target) > float(reference) + gap
    return float(target) < float(reference) - gap


def _crossed(direction: Direction, target: float, high: float, low: float) -> bool:
    if direction == Direction.BUY:
        return float(high) >= float(target)
    return float(low) <= float(target)


def _crossed_since(
    snapshot: MarketSnapshot,
    direction: Direction,
    target: float,
    start_ts: int,
) -> tuple[bool, int, str]:
    """Return conservative M15 evidence that an objective has already traded.

    The M15 bar containing start_ts is included. Its high/low can contain price
    action from just before the exact timestamp, so a crossing on that bar is
    deliberately treated as consumed/ambiguous rather than silently OPEN. That
    is fail-closed for execution and prevents a stale objective from being
    recycled after price has already traded through it.
    """
    if start_ts <= 0:
        return False, 0, "NO_START_TIMESTAMP"

    bars = sorted(list(snapshot.xau_m15 or []), key=lambda b: int(b.ts))
    for bar in bars:
        ts = int(bar.ts)
        if ts + _M15_SECONDS <= int(start_ts):
            continue
        if _crossed(direction, target, float(bar.high), float(bar.low)):
            basis = (
                "START_BAR_CROSS_OR_AMBIGUOUS"
                if ts < int(start_ts)
                else "POST_START_M15_CROSS"
            )
            return True, ts, basis
    return False, 0, "NO_CROSS"


def _history_complete(snapshot: MarketSnapshot, required_from: int) -> tuple[bool, int, str]:
    bars = sorted(list(snapshot.xau_m15 or []), key=lambda b: int(b.ts))
    if required_from <= 0:
        return False, 0, "NO_PUBLICATION_TIMESTAMP"
    if not bars:
        return False, 0, "NO_M15_HISTORY"
    first = int(bars[0].ts)
    if first > int(required_from):
        return False, first, "M15_HISTORY_STARTS_AFTER_PUBLICATION"
    return True, first, "OK"


def target_ladder_truth(
    analysis: Analysis | None,
    zone: Zone,
    snapshot: MarketSnapshot,
) -> dict[str, Any]:
    """Classify every original objective as OPEN, COMPLETED, or BEHIND_ACTIVATION_PRICE.

    Before ownership, the live quote is the provisional activation reference.
    A target already behind that reference is unavailable. A target that traded
    after exact-geometry publication is also unavailable even if price later
    retraces back across it.

    After ownership, the frozen ownership anchor is authoritative. Objective-hit
    metadata and best-price progress determine completion; targets that were
    already behind the ownership anchor are never relabelled as thesis profits.
    """
    direction = zone.original_direction
    meta = dict((analysis.execution_policy or {}).get("active_thesis") or {}) if analysis else {}
    is_owner = bool(
        meta.get("locked")
        and str(meta.get("owner_zone_id") or "") == zone.zone_id
        and str(meta.get("direction") or "") == direction.value
    )

    publication_ts = _note_int(zone, "geometry_published_at:", 0)
    ownership_ts = int(meta.get("ownership_acquired_at") or 0) if is_owner else 0
    ownership_anchor = float(meta.get("ownership_anchor_price") or 0.0) if is_owner else 0.0

    if is_owner and ownership_anchor > 0:
        activation_reference = ownership_anchor
        reference_basis = "OWNERSHIP_ANCHOR"
    else:
        activation_reference = float(snapshot.ask if direction == Direction.BUY else snapshot.bid)
        reference_basis = "LIVE_PRE_ENTRY_REFERENCE"

    history_complete, history_start_ts, history_reason = _history_complete(snapshot, publication_ts)
    gap = _target_gap(snapshot)
    best = float(meta.get("best_price") or 0.0) if is_owner else 0.0

    raw_targets = [
        ("TP1", 1, float(zone.original_target1 or 0.0)),
        ("TP2", 2, float(zone.original_target2 or 0.0)),
        ("TP3", 3, float(zone.original_target3 or 0.0)),
        ("RUNNER", 4, float(zone.original_runner or 0.0)),
    ]

    objectives: list[dict[str, Any]] = []
    for label, idx, price in raw_targets:
        if price <= 0:
            continue

        state = "OPEN"
        reason = "VERIFIED_OPEN"
        crossed_at = 0
        crossed_basis = ""

        if not _ahead(direction, price, activation_reference, gap):
            state = "BEHIND_ACTIVATION_PRICE"
            reason = f"{reference_basis}_ALREADY_BEYOND_OBJECTIVE"
        elif is_owner:
            hit_at = int(meta.get(f"target{idx}_hit_at") or 0) if idx <= 3 else 0
            crossed_best = bool(
                best > 0
                and (
                    (direction == Direction.SELL and best <= price)
                    or (direction == Direction.BUY and best >= price)
                )
            )
            crossed_live, live_ts, live_basis = _crossed_since(
                snapshot,
                direction,
                price,
                ownership_ts,
            ) if ownership_ts > 0 else (False, 0, "NO_OWNERSHIP_TIMESTAMP")
            if hit_at or crossed_best or crossed_live:
                state = "COMPLETED"
                crossed_at = hit_at or live_ts
                crossed_basis = (
                    "OWNER_TARGET_HIT"
                    if hit_at
                    else "OWNER_BEST_PRICE_CROSS"
                    if crossed_best
                    else live_basis
                )
                reason = crossed_basis
        else:
            crossed, crossed_at, crossed_basis = _crossed_since(
                snapshot,
                direction,
                price,
                publication_ts,
            )
            if crossed:
                state = "COMPLETED"
                reason = f"PRE_ENTRY_{crossed_basis}"
            elif not history_complete:
                reason = "OPEN_BUT_HISTORY_UNVERIFIED"

        objectives.append(
            {
                "label": label,
                "index": idx,
                "price": round(price, 5),
                "state": state,
                "reason": reason,
                "crossed_at": int(crossed_at or 0),
                "crossed_basis": crossed_basis,
            }
        )

    open_targets = [float(x["price"]) for x in objectives if x["state"] == "OPEN"]
    completed = [float(x["price"]) for x in objectives if x["state"] == "COMPLETED"]
    behind = [
        float(x["price"])
        for x in objectives
        if x["state"] == "BEHIND_ACTIVATION_PRICE"
    ]

    history_safe = True if is_owner else bool(history_complete)
    authority_safe = bool(open_targets) and history_safe

    if not history_safe:
        status = "HISTORY_UNVERIFIED_BLOCK"
    elif not open_targets:
        status = "REMAP_REQUIRED"
    else:
        status = "OPEN_TARGETS_AVAILABLE"

    return {
        "contract": TARGET_REVALIDATION_CONTRACT,
        "zone_id": zone.zone_id,
        "direction": direction.value,
        "owner": is_owner,
        "publication_ts": int(publication_ts),
        "ownership_acquired_at": int(ownership_ts),
        "activation_reference": round(float(activation_reference), 5),
        "activation_reference_basis": reference_basis,
        "history_complete": bool(history_complete),
        "history_start_ts": int(history_start_ts),
        "history_reason": history_reason,
        "objectives": objectives,
        "open_targets": open_targets,
        "completed_targets": completed,
        "behind_activation_targets": behind,
        "next_open_target": open_targets[0] if open_targets else 0.0,
        "authority_safe": authority_safe,
        "remap_required": not bool(open_targets),
        "status": status,
        "fail_closed": True,
        "invalidation_logic_unchanged": True,
    }


def apply_target_revalidation(analysis: Analysis, snapshot: MarketSnapshot) -> None:
    """Attach target truth to the analysis without changing zone/invalidation logic."""
    per_zone: dict[str, Any] = {}
    for zone in analysis.zones:
        per_zone[zone.zone_id] = target_ladder_truth(analysis, zone, snapshot)

    policy = dict(analysis.execution_policy or {})
    policy["target_revalidation"] = {
        "contract": TARGET_REVALIDATION_CONTRACT,
        "per_zone": per_zone,
        "new_execution_authority_requires_verified_open_target": True,
        "consumed_target_never_reopens_after_retrace": True,
        "no_open_target_requires_fresh_liquidity_remap": True,
        "zone_validity_independent_of_target_status": True,
        "invalidation_logic_unchanged": True,
    }
    analysis.execution_policy = policy

    selected = per_zone.get(str(analysis.selected_zone_id or ""))
    if selected:
        if selected["status"] == "REMAP_REQUIRED":
            analysis.trader_brief += (
                " Target-ladder revalidation: all published objectives are consumed "
                "or behind the activation reference; fresh liquidity remap is required "
                "before new execution authority."
            )
        elif selected["status"] == "HISTORY_UNVERIFIED_BLOCK":
            analysis.trader_brief += (
                " Target-ladder revalidation: objective history is incomplete; new "
                "execution authority is blocked until target truth can be verified."
            )
