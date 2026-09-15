from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .engine import atr
from .models import Analysis, Direction, LiquidityLevel, MarketSnapshot, Zone, ZoneState

TARGET_POLICY_CONTRACT = "INSTITUTIONAL_LIQUIDITY_OBJECTIVES_V657"


def _point(snapshot: MarketSnapshot) -> float:
    return max(abs(float(snapshot.point or 0.01)), 1e-9)


def _target_gap(snapshot: MarketSnapshot) -> float:
    """Minimum clearance so a structural target is not effectively at entry."""
    point = _point(snapshot)
    m15a = max(float(snapshot.atr_m15 or atr(snapshot.xau_m15)), point)
    return max(point * 10.0, point * float(snapshot.spread_points) * 1.50, 0.05 * m15a)


def _front_run_buffer(snapshot: MarketSnapshot) -> float:
    """Small buffer in front of an opposing HTF zone instead of targeting through it."""
    point = _point(snapshot)
    m15a = max(float(snapshot.atr_m15 or atr(snapshot.xau_m15)), point)
    return max(point * 10.0, point * float(snapshot.spread_points) * 1.50, 0.05 * m15a)


def _session_name(ts: int) -> str:
    """Approximate global session context from UTC; session never qualifies a zone."""
    hour = datetime.fromtimestamp(int(ts), tz=timezone.utc).hour
    if 0 <= hour < 7:
        return "ASIA"
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 16:
        return "LONDON_NY_OVERLAP"
    if 16 <= hour < 21:
        return "NEW_YORK"
    return "TRANSITION"


def _required_target_liquidity(direction: Direction) -> str:
    return "SSL" if direction == Direction.SELL else "BSL"


def _profit_side(direction: Direction, price: float, reference: float, gap: float) -> bool:
    if direction == Direction.SELL:
        return price < reference - gap
    return price > reference + gap


def _within_opposing_cap(direction: Direction, price: float, cap: float | None) -> bool:
    if cap is None:
        return True
    # Do not target through a still-active opposing institutional zone.
    if direction == Direction.SELL:
        return price >= cap - 1e-9
    return price <= cap + 1e-9


def _tf_rank(level: LiquidityLevel) -> int:
    return {"H1": 0, "H4": 1, "D1": 2}.get(str(level.source_tf).upper(), 9)


def _objective_kind(level: LiquidityLevel) -> str:
    label = str(level.label).upper()
    tf = str(level.source_tf).upper()
    if label in {"PDL", "PDH"}:
        return "PRIOR_DAY_LIQUIDITY"
    if tf == "D1":
        return "EXTERNAL_D1_LIQUIDITY"
    if tf == "H4":
        return "EXTERNAL_H4_LIQUIDITY"
    return "INTERNAL_H1_LIQUIDITY"


def _dedupe_levels(levels: list[LiquidityLevel], snapshot: MarketSnapshot) -> list[LiquidityLevel]:
    tolerance = max(_point(snapshot) * 10.0, 0.10)
    out: list[LiquidityLevel] = []
    for level in levels:
        if any(abs(float(level.price) - float(x.price)) <= tolerance for x in out):
            continue
        out.append(level)
    return out


def _structural_levels(
    analysis: Analysis,
    snapshot: MarketSnapshot,
    direction: Direction,
    reference: float,
    cap: float | None,
) -> list[LiquidityLevel]:
    required = _required_target_liquidity(direction)
    gap = _target_gap(snapshot)
    out: list[LiquidityLevel] = []
    for level in analysis.liquidity_map:
        label = str(level.label).upper()
        tf = str(level.source_tf).upper()
        if required not in label and not (direction == Direction.SELL and label == "PDL") and not (direction == Direction.BUY and label == "PDH"):
            continue
        if tf not in {"H1", "H4", "D1"} and label not in {"PDL", "PDH"}:
            continue
        price = float(level.price)
        if not _profit_side(direction, price, reference, gap):
            continue
        if not _within_opposing_cap(direction, price, cap):
            continue
        out.append(level)

    out.sort(key=lambda x: abs(float(x.price) - reference))
    return _dedupe_levels(out, snapshot)


def _opposing_primary(analysis: Analysis, zone: Zone) -> Zone | None:
    for other in analysis.zones:
        if other.zone_id == zone.zone_id:
            continue
        if other.original_direction == zone.original_direction.opposite() and other.state == ZoneState.ACTIVE:
            return other
    return None


def _opposing_cap(zone: Zone, analysis: Analysis, snapshot: MarketSnapshot) -> tuple[float | None, dict[str, Any] | None]:
    opposing = _opposing_primary(analysis, zone)
    if opposing is None:
        return None, None
    buffer_price = _front_run_buffer(snapshot)
    if zone.original_direction == Direction.SELL:
        price = float(opposing.zone_high) + buffer_price
        if price >= float(zone.core_low):
            return None, None
    else:
        price = float(opposing.zone_low) - buffer_price
        if price <= float(zone.core_high):
            return None, None
    return price, {
        "price": round(price, 5),
        "kind": "OPPOSING_ZONE_PROXIMAL_FRONT_RUN",
        "zone_id": opposing.zone_id,
        "zone_side": opposing.original_direction.value,
        "buffer": round(buffer_price, 5),
    }


def _append_distinct(values: list[dict[str, Any]], item: dict[str, Any], snapshot: MarketSnapshot) -> None:
    tolerance = max(_point(snapshot) * 10.0, 0.10)
    price = float(item["price"])
    if any(abs(price - float(x["price"])) <= tolerance for x in values):
        return
    values.append(item)


def _build_original_ladder(zone: Zone, analysis: Analysis, snapshot: MarketSnapshot) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    direction = zone.original_direction
    # Use the least-favourable edge of the core so every exported objective is
    # profitable from any legitimate core entry, not only from the midpoint.
    reference = float(zone.core_low) if direction == Direction.SELL else float(zone.core_high)
    cap, opposing_meta = _opposing_cap(zone, analysis, snapshot)
    levels = _structural_levels(analysis, snapshot, direction, reference, cap)

    objectives: list[dict[str, Any]] = []
    if levels:
        nearest = levels[0]
        _append_distinct(objectives, {
            "price": float(nearest.price),
            "kind": _objective_kind(nearest),
            "label": nearest.label,
            "source_tf": nearest.source_tf,
        }, snapshot)

    # TP2 prefers a deeper H4/D1/prior-day pool rather than another tiny nearby
    # H1 pivot. If none exists, use the next distinct structural pool.
    deeper = levels[1:]
    external = next((x for x in deeper if str(x.source_tf).upper() in {"H4", "D1"} or str(x.label).upper() in {"PDL", "PDH"}), None)
    second = external or (deeper[0] if deeper else None)
    if second is not None:
        _append_distinct(objectives, {
            "price": float(second.price),
            "kind": _objective_kind(second),
            "label": second.label,
            "source_tf": second.source_tf,
        }, snapshot)

    # An active opposing zone is the natural destination of the move. Take the
    # final planned objective just in front of it; do not automatically target
    # through a valid opposing institutional area.
    if opposing_meta is not None:
        _append_distinct(objectives, opposing_meta, snapshot)
    else:
        for level in deeper:
            _append_distinct(objectives, {
                "price": float(level.price),
                "kind": _objective_kind(level),
                "label": level.label,
                "source_tf": level.source_tf,
            }, snapshot)
            if len(objectives) >= 4:
                break

    # Preserve the actual path order from entry outward.
    objectives.sort(key=lambda x: abs(float(x["price"]) - reference))
    return objectives[:4], opposing_meta


def _build_flip_ladder(zone: Zone, analysis: Analysis, snapshot: MarketSnapshot) -> list[dict[str, Any]]:
    direction = zone.flip_direction
    reference = float(zone.zone_high) if direction == Direction.BUY else float(zone.zone_low)
    levels = _structural_levels(analysis, snapshot, direction, reference, None)
    return [
        {
            "price": float(level.price),
            "kind": _objective_kind(level),
            "label": level.label,
            "source_tf": level.source_tf,
        }
        for level in levels[:4]
    ]


def _set_zone_targets(zone: Zone, objectives: list[dict[str, Any]], flip_objectives: list[dict[str, Any]]) -> None:
    vals = [float(x["price"]) for x in objectives] + [0.0] * 4
    fvals = [float(x["price"]) for x in flip_objectives] + [0.0] * 4
    zone.original_target1 = vals[0]
    zone.original_target2 = vals[1]
    zone.original_target3 = vals[2]
    zone.original_runner = vals[3]
    zone.flip_target1 = fvals[0]
    zone.flip_target2 = fvals[1]
    zone.flip_target3 = fvals[2]
    zone.flip_runner = fvals[3]
    reference = float(zone.core_low) if zone.original_direction == Direction.SELL else float(zone.core_high)
    zone.clear_run = round(abs(float(vals[0]) - reference), 5) if vals[0] else 0.0


def apply_liquidity_objective_policy(analysis: Analysis, snapshot: MarketSnapshot) -> None:
    """Replace nearest-price TPs with institutional liquidity objectives.

    Zone validity remains solely a location/structure/M15 question. A weak or
    missing objective ladder may block execution, but it must never delete or
    move an otherwise valid institutional zone.
    """
    session = _session_name(snapshot.sent_at)
    zone_details: dict[str, Any] = {}

    for zone in analysis.zones:
        objectives, opposing_meta = _build_original_ladder(zone, analysis, snapshot)
        flip_objectives = _build_flip_ladder(zone, analysis, snapshot)
        _set_zone_targets(zone, objectives, flip_objectives)

        zone.notes = [n for n in zone.notes if not str(n).startswith("liquidity_objective_policy:")]
        zone.notes.append(f"liquidity_objective_policy:{TARGET_POLICY_CONTRACT}")
        zone_details[zone.zone_id] = {
            "direction": zone.original_direction.value,
            "objectives": objectives,
            "flip_objectives": flip_objectives,
            "opposing_zone_cap": opposing_meta,
            "zone_validity_independent_of_target_map": True,
        }

    policy = dict(analysis.execution_policy or {})
    policy["liquidity_objectives"] = {
        "contract": TARGET_POLICY_CONTRACT,
        "session": session,
        "session_reference": "UTC_APPROXIMATE",
        "asia_policy": "VALID_ZONE_REMAINS_VALID; PATIENT_LIQUIDITY_LADDER; NO_FORCED_EARLY_EXIT",
        "zone_validity_independent_of_targets": True,
        "tp1": "NEAREST_VALID_INTERNAL_OR_STRUCTURAL_LIQUIDITY",
        "tp2": "DEEPER_H4_D1_OR_PRIOR_DAY_LIQUIDITY",
        "tp3": "FRONT_RUN_ACTIVE_OPPOSING_PRIMARY_ZONE_WHEN_PRESENT",
        "runner": "ONLY_BEYOND_OPPOSING_ZONE_AFTER_FRESH_INVALIDATION_REQUALIFICATION",
        "stop_rule": "M1_SWEEP_EXTREME_PLUS_SMALL_SPREAD_ATR_BUFFER; HTF_ENVELOPE_IS_THESIS_INVALIDATION_NOT_DEFAULT_STOP",
        "no_target_through_active_opposing_zone": True,
        "per_zone": zone_details,
    }
    analysis.execution_policy = policy

    summaries: list[str] = []
    for zone in analysis.zones:
        targets = [zone.original_target1, zone.original_target2, zone.original_target3]
        shown = "/".join(f"{x:.2f}" for x in targets if x > 0)
        if shown:
            summaries.append(f"{zone.original_direction.value} objectives={shown}")
    if summaries:
        analysis.trader_brief += " Liquidity-objective ladder: " + "; ".join(summaries) + f". Session={session}; session changes patience, not zone validity."
