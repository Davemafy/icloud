from __future__ import annotations

from .config import SETTINGS
from .engine import GRADE_RANK, _touches, atr, evaluate_zone_state
from .intraday_engine import build_candidates
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState


CORE_INTERACTION_BUFFER_M15_ATR = 0.30
H4_ENVELOPE_HALF_M15_ATR = 0.60
H4H1_ENVELOPE_HALF_M15_ATR = 0.40
H1_ENVELOPE_HALF_M15_ATR = 0.25


def _readiness(zone: Zone) -> str:
    value = str(zone.core_method or "")
    return value.split("|", 1)[0] if "|" in value else "WATCH"


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _candidate_map(s: MarketSnapshot):
    out = {}
    for index, candidate in enumerate(build_candidates(s), 1):
        zid = f"Z_{candidate.source_tf.replace('>','')}_{candidate.direction.value}_{index}"
        out[zid] = candidate
    return out


def _resting_liquidity(zone: Zone, analysis: Analysis, s: MarketSnapshot) -> bool:
    h1a = s.atr_h1 or atr(s.xau_h1)
    h4a = atr(s.xau_h4)
    cap = max(1e-9, min(1.50 * h1a, 0.75 * h4a))
    mid = (float(zone.core_low) + float(zone.core_high)) / 2.0
    if zone.original_direction == Direction.SELL:
        return any(
            level.price >= zone.core_high and level.price - mid <= cap
            for level in analysis.liquidity_map
        )
    return any(
        level.price <= zone.core_low and mid - level.price <= cap
        for level in analysis.liquidity_map
    )


def _parent_ts(zone: Zone, candidate) -> int:
    if candidate is None:
        return int(zone.source_ts)
    h4 = [int(x.source_ts) for x in candidate.components if str(x.tf) == "H4"]
    return max(h4) if h4 else int(candidate.source_ts)


def _core_touches(zone: Zone, candidate, s: MarketSnapshot) -> int:
    source_ts = int(candidate.source_ts) if candidate is not None else int(zone.source_ts)
    return _touches(
        float(zone.core_low),
        float(zone.core_high),
        source_ts,
        s.xau_m15,
    )


def _compact_envelope(zone: Zone, s: MarketSnapshot) -> None:
    """Keep liquidity as a qualification reference, not an envelope stretcher."""
    m15a = max(float(s.atr_m15 or atr(s.xau_m15)), 1e-9)
    mid = (float(zone.core_low) + float(zone.core_high)) / 2.0
    if zone.source_tf == "H4":
        half = H4_ENVELOPE_HALF_M15_ATR * m15a
    elif zone.source_tf == "H4>H1":
        half = H4H1_ENVELOPE_HALF_M15_ATR * m15a
    else:
        half = H1_ENVELOPE_HALF_M15_ATR * m15a

    low = min(float(zone.core_low), mid - half)
    high = max(float(zone.core_high), mid + half)
    zone.zone_low = round(low, 5)
    zone.zone_high = round(high, 5)
    zone.invalidation_level = round(
        high if zone.original_direction == Direction.SELL else low,
        5,
    )
    zone.invalidation_rule = (
        "M15 accepted body beyond compact institutional envelope: one >=60% body "
        "and >=0.40 ATR, or two closes each >=0.20 ATR. Wick-only does not invalidate."
    )
    zone.notes = [
        note for note in zone.notes
        if not str(note).startswith("m15_min_width_expansion:")
    ]
    if "LIQUIDITY_REFERENCE_ONLY_DOES_NOT_STRETCH_ZONE" not in zone.notes:
        zone.notes.append("LIQUIDITY_REFERENCE_ONLY_DOES_NOT_STRETCH_ZONE")


def _institutional_rank(zone: Zone, analysis: Analysis, s: MarketSnapshot, candidate) -> tuple:
    touches = _core_touches(zone, candidate, s)
    has_liq = _resting_liquidity(zone, analysis, s)
    parent = zone.source_tf in {"H4", "H4>H1"}

    # Primary institutional preference:
    # 1) fresh H4 parent + resting liquidity,
    # 2) lightly-touched H4 parent,
    # 3) tactical H1 fallback.
    if parent and touches == 0 and has_liq:
        tier = 0
    elif parent and touches <= 1:
        tier = 1
    elif zone.source_tf == "H1" and touches <= 1:
        tier = 2
    else:
        tier = 3

    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(zone.source_tf, 9)
    grade_rank = GRADE_RANK.get(zone.grade, 9)
    distance = _distance(float(s.mid), float(zone.core_low), float(zone.core_high))
    return (
        tier,
        tf_rank,
        -_parent_ts(zone, candidate),
        touches,
        0 if has_liq else 1,
        grade_rank,
        -float(zone.location_score),
        distance,
    )


def primary_zone_interacting(zone: Zone, s: MarketSnapshot) -> bool:
    if not SETTINGS.paper_only:
        return False
    if zone.state != ZoneState.ACTIVE:
        return False
    if zone.grade not in {Grade.A_PLUS, Grade.A}:
        return False
    if _readiness(zone) not in {"ACTIONABLE", "WATCH", "M1_READY"}:
        return False
    state = evaluate_zone_state(zone, s.xau_m15, s.atr_m15)
    if state != ZoneState.ACTIVE:
        return False
    m15a = max(float(s.atr_m15 or atr(s.xau_m15)), 1e-9)
    buffer_price = max(float(s.point) * 5.0, CORE_INTERACTION_BUFFER_M15_ATR * m15a)
    return _distance(float(s.mid), float(zone.core_low), float(zone.core_high)) <= buffer_price


def apply_two_zone_institutional_map(analysis: Analysis, s: MarketSnapshot) -> list[Zone]:
    """Reduce the public market map to one institutional BUY and one SELL zone.

    Internal candidate discovery remains unchanged. The public dashboard and paper
    execution handoff receive only the strongest zone on each side, with H4 parent
    quality/freshness/liquidity ranked ahead of mere proximity.
    """
    if analysis is None or not analysis.zones:
        return []

    cmap = _candidate_map(s)
    chosen: dict[Direction, Zone] = {}
    for direction in (Direction.BUY, Direction.SELL):
        side = [z for z in analysis.zones if z.original_direction == direction]
        if not side:
            continue
        side.sort(
            key=lambda z: _institutional_rank(
                z, analysis, s, cmap.get(z.zone_id)
            )
        )
        zone = side[0]
        candidate = cmap.get(zone.zone_id)
        zone.touch_count = _core_touches(zone, candidate, s)
        _compact_envelope(zone, s)
        zone.state = evaluate_zone_state(zone, s.xau_m15, s.atr_m15)
        if "PRIMARY_INSTITUTIONAL_ZONE" not in zone.notes:
            zone.notes.append("PRIMARY_INSTITUTIONAL_ZONE")
        if _resting_liquidity(zone, analysis, s):
            conf = set(zone.confluences)
            conf.add("RESTING_LIQUIDITY")
            zone.confluences = sorted(conf)
            zone.independent_confluence_count = len(conf)
        chosen[direction] = zone

    order = (
        [Direction.SELL, Direction.BUY]
        if analysis.overall_bias == Direction.SELL
        else [Direction.BUY, Direction.SELL]
        if analysis.overall_bias == Direction.BUY
        else [Direction.SELL, Direction.BUY]
    )
    analysis.zones = [chosen[d] for d in order if d in chosen]

    # Never keep a selected zone that was removed by the two-zone filter.
    if analysis.selected_zone_id and not any(
        z.zone_id == analysis.selected_zone_id for z in analysis.zones
    ):
        analysis.selected_zone_id = ""

    # If price is already interacting with one of the two execution-qualified
    # zones, make that zone authoritative for the paper plan.
    interacting = [z for z in analysis.zones if primary_zone_interacting(z, s)]
    if interacting:
        interacting.sort(
            key=lambda z: (
                _distance(float(s.mid), float(z.core_low), float(z.core_high)),
                0 if z.grade == Grade.A_PLUS else 1,
                -float(z.location_score),
            )
        )
        analysis.selected_zone_id = interacting[0].zone_id

    labels = []
    for z in analysis.zones:
        role = "TREND" if not z.countertrend else "REVERSAL"
        labels.append(
            f"{role} {z.original_direction.value}={z.zone_low:.2f}-{z.zone_high:.2f} "
            f"({z.grade.value},{_readiness(z)})"
        )
    summary = "; ".join(labels) if labels else "none"
    analysis.trader_brief = (
        f"D1 context={analysis.overall_bias.value}. Two-zone institutional map only: {summary}. "
        "H4 parent location/freshness/resting liquidity outrank proximity; H1/M15 refine quality; "
        "M1 sweep/MSS/displacement/value confirmation remains mandatory."
    )

    policy = dict(analysis.execution_policy or {})
    policy["public_zone_map"] = {
        "max_zones": 2,
        "one_per_side": True,
        "h4_parent_priority": True,
        "resting_liquidity_qualifies_not_expands": True,
        "core_mitigation_authoritative": True,
        "m1_confirmation_unchanged": True,
    }
    analysis.execution_policy = policy
    return analysis.zones
