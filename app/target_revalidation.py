from __future__ import annotations

from typing import Any

from .models import Analysis, Direction, MarketSnapshot, Zone

TARGET_REVALIDATION_CONTRACT = "TARGET_LADDER_OWNER_OPPOSING_CAP_V65107"
_M15_SECONDS = 15 * 60


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
    if start_ts <= 0:
        return False, 0, "NO_ACTIVATION_TIMESTAMP"

    bars = sorted(list(snapshot.xau_m15 or []), key=lambda b: int(b.ts))
    for bar in bars:
        ts = int(bar.ts)
        if ts + _M15_SECONDS <= int(start_ts):
            continue
        if _crossed(direction, target, float(bar.high), float(bar.low)):
            basis = (
                "ACTIVATION_BAR_CROSS_OR_AMBIGUOUS"
                if ts < int(start_ts)
                else "POST_ACTIVATION_M15_CROSS"
            )
            return True, ts, basis
    return False, 0, "NO_CROSS"


def _raw_targets(zone: Zone) -> list[tuple[str, int, float]]:
    return [
        ("TP1", 1, float(zone.original_target1 or 0.0)),
        ("TP2", 2, float(zone.original_target2 or 0.0)),
        ("TP3", 3, float(zone.original_target3 or 0.0)),
        ("RUNNER", 4, float(zone.original_runner or 0.0)),
    ]


def planned_target_truth(zone: Zone) -> dict[str, Any]:
    """Return pre-activation target truth.

    A published zone is only a PLAN until an execution handoff actually acquires
    thesis ownership. Price may trade through its future TP levels before the zone
    is ever reached; those crossings do NOT consume the targets because no trade
    thesis was active from that zone.
    """
    objectives = [
        {
            "label": label,
            "index": idx,
            "price": round(price, 5),
            "state": "PLANNED",
            "reason": "ZONE_NOT_ACTIVATED",
            "crossed_at": 0,
            "crossed_basis": "",
        }
        for label, idx, price in _raw_targets(zone)
        if price > 0
    ]
    planned = [float(x["price"]) for x in objectives]
    return {
        "contract": TARGET_REVALIDATION_CONTRACT,
        "zone_id": zone.zone_id,
        "direction": zone.original_direction.value,
        "owner": False,
        "activated": False,
        "activation_reference": 0.0,
        "activation_reference_basis": "NONE_UNTIL_EXECUTION_HANDOFF",
        "activation_ts": 0,
        "history_complete": True,
        "history_reason": "PRE_ACTIVATION_HISTORY_NOT_APPLICABLE",
        "objectives": objectives,
        "planned_targets": planned,
        "open_targets": [],
        "completed_targets": [],
        "behind_activation_targets": [],
        "next_open_target": 0.0,
        "authority_safe": False,
        "execution_evaluable": False,
        "remap_required": False,
        "status": "PLANNED_NOT_ACTIVATED",
        "pre_activation_crossings_consume_targets": False,
        "invalidation_logic_unchanged": True,
    }


def activation_target_truth(
    zone: Zone,
    snapshot: MarketSnapshot,
    activation_reference: float,
    *,
    activation_ts: int = 0,
    reference_basis: str = "EXECUTION_HANDOFF_ANCHOR",
) -> dict[str, Any]:
    """Evaluate the planned ladder at the instant execution authority activates.

    Only now do TP levels become execution objectives. A level already behind the
    activation price is unavailable; a level still on the profit side is OPEN.
    Market travel before activation is intentionally ignored.
    """
    reference = float(activation_reference)
    gap = _target_gap(snapshot)
    objectives: list[dict[str, Any]] = []
    for label, idx, price in _raw_targets(zone):
        if price <= 0:
            continue
        if _ahead(zone.original_direction, price, reference, gap):
            state = "OPEN"
            reason = "OPEN_AT_ACTIVATION"
        else:
            state = "BEHIND_ACTIVATION_PRICE"
            reason = f"{reference_basis}_ALREADY_BEYOND_OBJECTIVE"
        objectives.append(
            {
                "label": label,
                "index": idx,
                "price": round(price, 5),
                "state": state,
                "reason": reason,
                "crossed_at": 0,
                "crossed_basis": "",
            }
        )

    open_targets = [float(x["price"]) for x in objectives if x["state"] == "OPEN"]
    behind = [
        float(x["price"])
        for x in objectives
        if x["state"] == "BEHIND_ACTIVATION_PRICE"
    ]
    return {
        "contract": TARGET_REVALIDATION_CONTRACT,
        "zone_id": zone.zone_id,
        "direction": zone.original_direction.value,
        "owner": False,
        "activated": True,
        "activation_reference": round(reference, 5),
        "activation_reference_basis": reference_basis,
        "activation_ts": int(activation_ts or snapshot.sent_at),
        "history_complete": True,
        "history_reason": "ACTIVATION_STARTS_TARGET_LIFECYCLE",
        "objectives": objectives,
        "planned_targets": [float(x["price"]) for x in objectives],
        "open_targets": open_targets,
        "completed_targets": [],
        "behind_activation_targets": behind,
        "next_open_target": open_targets[0] if open_targets else 0.0,
        "authority_safe": bool(open_targets),
        "execution_evaluable": True,
        "remap_required": not bool(open_targets),
        "status": "OPEN_TARGETS_AVAILABLE" if open_targets else "REMAP_REQUIRED_AT_ACTIVATION",
        "pre_activation_crossings_consume_targets": False,
        "invalidation_logic_unchanged": True,
    }


def _beyond_owner_cap(direction: Direction, price: float, cap: float) -> bool:
    if cap <= 0 or price <= 0:
        return False
    if direction == Direction.BUY:
        return price > cap + 1e-9
    return price < cap - 1e-9


def _quote_crossed(direction: Direction, price: float, snapshot: MarketSnapshot) -> bool:
    if price <= 0:
        return False
    if direction == Direction.BUY:
        return float(snapshot.bid) >= price
    return float(snapshot.ask) <= price


def _crossed_since_cap_set(
    snapshot: MarketSnapshot,
    direction: Direction,
    target: float,
    set_at: int,
) -> tuple[bool, int, str]:
    """Cap truth is prospective: ignore every M15 bar that began before cap creation."""
    if set_at <= 0:
        return False, 0, "NO_CAP_SET_TIMESTAMP"
    for bar in sorted(list(snapshot.xau_m15 or []), key=lambda b: int(b.ts)):
        ts = int(bar.ts)
        if ts < int(set_at):
            continue
        if _crossed(direction, target, float(bar.high), float(bar.low)):
            return True, ts, "POST_CAP_M15_CROSS"
    return False, 0, "NO_POST_CAP_CROSS"


def owner_target_truth(
    analysis: Analysis,
    zone: Zone,
    snapshot: MarketSnapshot,
) -> dict[str, Any]:
    meta = dict((analysis.execution_policy or {}).get("active_thesis") or {})
    ownership_ts = int(meta.get("ownership_acquired_at") or 0)
    ownership_anchor = float(meta.get("ownership_anchor_price") or 0.0)
    if ownership_anchor <= 0:
        ownership_anchor = float(
            snapshot.ask if zone.original_direction == Direction.BUY else snapshot.bid
        )

    truth = activation_target_truth(
        zone,
        snapshot,
        ownership_anchor,
        activation_ts=ownership_ts,
        reference_basis="OWNERSHIP_ANCHOR",
    )
    truth["owner"] = True

    best = float(meta.get("best_price") or 0.0)
    objectives: list[dict[str, Any]] = []
    for item in list(truth["objectives"]):
        current = dict(item)
        idx = int(current.get("index") or 0)
        price = float(current.get("price") or 0.0)

        if current.get("state") == "OPEN":
            hit_at = int(meta.get(f"target{idx}_hit_at") or 0) if idx <= 3 else 0
            crossed_best = bool(
                best > 0
                and (
                    (
                        zone.original_direction == Direction.SELL
                        and best <= price
                    )
                    or (
                        zone.original_direction == Direction.BUY
                        and best >= price
                    )
                )
            )
            crossed_live, live_ts, live_basis = (
                _crossed_since(
                    snapshot,
                    zone.original_direction,
                    price,
                    ownership_ts,
                )
                if ownership_ts > 0
                else (False, 0, "NO_ACTIVATION_TIMESTAMP")
            )
            if hit_at or crossed_best or crossed_live:
                current["state"] = "COMPLETED"
                current["crossed_at"] = int(hit_at or live_ts or 0)
                current["crossed_basis"] = (
                    "OWNER_TARGET_HIT"
                    if hit_at
                    else "OWNER_BEST_PRICE_CROSS"
                    if crossed_best
                    else live_basis
                )
                current["reason"] = current["crossed_basis"]

        objectives.append(current)

    cap = float(meta.get("ownership_objective_cap") or 0.0)
    cap_zone_id = str(meta.get("ownership_objective_cap_zone_id") or "")
    cap_set_at = int(meta.get("ownership_objective_cap_set_at") or 0)
    cap_reached_at = int(meta.get("ownership_objective_cap_reached_at") or 0)
    blocked_by_cap: list[float] = []

    if cap > 0 and cap_set_at > 0:
        for current in objectives:
            if current.get("state") != "OPEN":
                continue
            price = float(current.get("price") or 0.0)
            if _beyond_owner_cap(zone.original_direction, price, cap):
                current["state"] = "BLOCKED_BY_OPPOSING_ZONE_CAP"
                current["reason"] = "FROZEN_TARGET_BEYOND_ACTIVE_OPPOSING_PRIMARY"
                blocked_by_cap.append(price)

        crossed_live, live_ts, live_basis = _crossed_since_cap_set(
            snapshot,
            zone.original_direction,
            cap,
            cap_set_at,
        )
        quote_crossed = bool(
            int(snapshot.sent_at) >= cap_set_at
            and _quote_crossed(zone.original_direction, cap, snapshot)
        )
        cap_complete = bool(cap_reached_at or crossed_live or quote_crossed)
        cap_crossed_at = int(
            cap_reached_at
            or live_ts
            or (int(snapshot.sent_at) if quote_crossed else 0)
        )
        cap_basis = (
            "OWNER_OBJECTIVE_CAP_REACHED"
            if cap_reached_at
            else live_basis
            if crossed_live
            else "LIVE_QUOTE_CROSS_AFTER_CAP_SET"
            if quote_crossed
            else ""
        )
        objectives.append(
            {
                "label": "OWNER_CAP",
                "index": 99,
                "price": round(cap, 5),
                "state": "COMPLETED" if cap_complete else "OPEN",
                "reason": (
                    cap_basis
                    if cap_complete
                    else "ACTIVE_OPPOSING_PRIMARY_PROXIMAL_FRONT_RUN"
                ),
                "crossed_at": cap_crossed_at,
                "crossed_basis": cap_basis,
                "opposing_zone_id": cap_zone_id,
                "lifecycle_only_tightening": True,
            }
        )

    open_targets = sorted(
        [float(x["price"]) for x in objectives if x["state"] == "OPEN"],
        key=lambda price: abs(float(price) - ownership_anchor),
    )
    completed = sorted(
        [float(x["price"]) for x in objectives if x["state"] == "COMPLETED"],
        key=lambda price: abs(float(price) - ownership_anchor),
    )
    behind = [
        float(x["price"])
        for x in objectives
        if x["state"] == "BEHIND_ACTIVATION_PRICE"
    ]

    truth.update(
        {
            "objectives": objectives,
            "open_targets": open_targets,
            "completed_targets": completed,
            "behind_activation_targets": behind,
            "blocked_by_opposing_zone_cap": blocked_by_cap,
            "next_open_target": open_targets[0] if open_targets else 0.0,
            "authority_safe": bool(open_targets),
            "execution_evaluable": True,
            "remap_required": not bool(open_targets),
            "status": (
                "ACTIVE_TARGETS_OPEN"
                if open_targets
                else "ACTIVE_TARGETS_COMPLETE_OR_EXHAUSTED"
            ),
            "history_reason": (
                "TARGET_LIFECYCLE_OWNER_CAP_RECONCILED"
                if cap > 0
                else "TARGET_LIFECYCLE_STARTED_AT_OWNERSHIP"
            ),
            "owner_objective_cap_active": bool(cap > 0 and cap_set_at > 0),
            "owner_objective_cap": round(cap, 5) if cap > 0 else 0.0,
            "owner_objective_cap_zone_id": cap_zone_id,
            "owner_objective_cap_set_at": cap_set_at,
            "owner_objective_cap_reached_at": cap_reached_at,
            "frozen_owner_targets_preserved": True,
            "live_position_targets_mutated": False,
        }
    )
    return truth


def target_ladder_truth(
    analysis: Analysis | None,
    zone: Zone,
    snapshot: MarketSnapshot,
) -> dict[str, Any]:
    """Return PLAN truth before activation and lifecycle truth after activation."""
    if analysis is None:
        return planned_target_truth(zone)

    meta = dict((analysis.execution_policy or {}).get("active_thesis") or {})
    is_owner = bool(
        meta.get("locked")
        and str(meta.get("owner_zone_id") or "") == zone.zone_id
        and str(meta.get("direction") or "") == zone.original_direction.value
    )
    if not is_owner:
        return planned_target_truth(zone)
    return owner_target_truth(analysis, zone, snapshot)


def apply_target_revalidation(analysis: Analysis, snapshot: MarketSnapshot) -> None:
    """Attach target lifecycle truth without changing zone/invalidation logic."""
    per_zone: dict[str, Any] = {}
    for zone in analysis.zones:
        per_zone[zone.zone_id] = target_ladder_truth(analysis, zone, snapshot)

    policy = dict(analysis.execution_policy or {})
    policy["target_revalidation"] = {
        "contract": TARGET_REVALIDATION_CONTRACT,
        "per_zone": per_zone,
        "target_lifecycle_begins_at_execution_activation": True,
        "pre_activation_crossings_consume_targets": False,
        "new_execution_authority_checks_targets_at_handoff_anchor": True,
        "owner_objective_cap_one_way_tightening_only": True,
        "owner_cap_requires_flat_sequence_truth": True,
        "owner_frozen_targets_remain_audit_truth": True,
        "live_position_targets_are_never_mutated_by_cap_reconciliation": True,
        "zone_validity_independent_of_target_status": True,
        "invalidation_logic_unchanged": True,
    }
    analysis.execution_policy = policy

    selected = per_zone.get(str(analysis.selected_zone_id or ""))
    if selected and selected.get("status") == "ACTIVE_TARGETS_COMPLETE_OR_EXHAUSTED":
        analysis.trader_brief += (
            " Target-ladder lifecycle: the active thesis has no remaining open "
            "objective; no further same-thesis entry is allowed."
        )
