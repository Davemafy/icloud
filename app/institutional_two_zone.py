from __future__ import annotations

from .config import SETTINGS
from .engine import GRADE_RANK, _touches, atr, evaluate_zone_state
from .intraday_engine import _zone as build_zone
from .intraday_engine import build_candidates, daily_context
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState


CORE_INTERACTION_BUFFER_M15_ATR = 0.30
H4_ENVELOPE_HALF_M15_ATR = 0.60
H4H1_ENVELOPE_HALF_M15_ATR = 0.40
H1_ENVELOPE_HALF_M15_ATR = 0.25
H4_PARENT_SOURCES = {"H4", "H4>H1"}
MAX_PRIMARY_PARENT_REACTIONS = 1


def _readiness(zone: Zone) -> str:
    value = str(zone.core_method or "")
    return value.split("|", 1)[0] if "|" in value else "WATCH"


def _replace_readiness(zone: Zone, readiness: str) -> None:
    old = str(zone.core_method or "")
    tail = old.split("|", 1)[1] if "|" in old else old
    zone.core_method = readiness if not tail else f"{readiness}|{tail}"
    zone.notes = [
        f"readiness:{readiness}" if str(note).startswith("readiness:") else note
        for note in zone.notes
    ]
    if not any(str(note).startswith("readiness:") for note in zone.notes):
        zone.notes = [f"readiness:{readiness}", *zone.notes]


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _candidate_rows(s: MarketSnapshot):
    rows = []
    for index, candidate in enumerate(build_candidates(s), 1):
        zid = f"Z_{candidate.source_tf.replace('>','')}_{candidate.direction.value}_{index}"
        rows.append((zid, index, candidate))
    return rows


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


def _max_strength(candidate) -> float:
    if candidate is None or not candidate.components:
        return 0.0
    return max(float(x.strength) for x in candidate.components)


def _core_touches(zone: Zone, candidate, s: MarketSnapshot) -> int:
    source_ts = int(candidate.source_ts) if candidate is not None else int(zone.source_ts)
    return _touches(
        float(zone.core_low),
        float(zone.core_high),
        source_ts,
        s.xau_m15,
    )


def _compact_envelope(zone: Zone, s: MarketSnapshot) -> None:
    """Keep liquidity as a qualification reference, never an envelope stretcher."""
    m15a = max(float(s.atr_m15 or atr(s.xau_m15)), 1e-9)
    mid = (float(zone.core_low) + float(zone.core_high)) / 2.0
    if zone.source_tf == "H4":
        half = H4_ENVELOPE_HALF_M15_ATR * m15a
    elif zone.source_tf == "H4>H1":
        half = H4H1_ENVELOPE_HALF_M15_ATR * m15a
    else:
        half = H1_ENVELOPE_HALF_M15_ATR * m15a

    zone.zone_low = round(min(float(zone.core_low), mid - half), 5)
    zone.zone_high = round(max(float(zone.core_high), mid + half), 5)
    zone.invalidation_level = round(
        zone.zone_high if zone.original_direction == Direction.SELL else zone.zone_low,
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
    touches = int(zone.touch_count)
    has_liq = _resting_liquidity(zone, analysis, s)
    parent = zone.source_tf in H4_PARENT_SOURCES
    strength = _max_strength(candidate)
    displaced = "INSTITUTIONAL_DISPLACEMENT" in zone.confluences or strength >= 2.0

    # H4 parent authority is absolute over an H1-only fallback while the parent
    # remains active. A single clean rejection remains valid; repeated visits do not.
    if parent and has_liq and touches == 0:
        tier = 0
    elif parent and has_liq and touches == 1:
        tier = 1
    elif parent and touches <= MAX_PRIMARY_PARENT_REACTIONS:
        tier = 2
    elif zone.source_tf == "H1" and has_liq and touches <= 1:
        tier = 3
    elif zone.source_tf == "H1" and touches <= 1:
        tier = 4
    else:
        tier = 9

    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(zone.source_tf, 9)
    grade_rank = GRADE_RANK.get(zone.grade, 9)
    distance = _distance(float(s.mid), float(zone.core_low), float(zone.core_high))
    return (
        tier,
        tf_rank,
        0 if displaced else 1,
        grade_rank,
        -float(zone.location_score),
        -strength,
        touches,
        distance,
        -_parent_ts(zone, candidate),
    )


def _interaction_now(zone: Zone, s: MarketSnapshot) -> bool:
    if not SETTINGS.paper_only or zone.state != ZoneState.ACTIVE:
        return False
    if zone.grade not in {Grade.A_PLUS, Grade.A}:
        return False
    state = evaluate_zone_state(zone, s.xau_m15, s.atr_m15)
    if state != ZoneState.ACTIVE:
        return False
    m15a = max(float(s.atr_m15 or atr(s.xau_m15)), 1e-9)
    buffer_price = max(float(s.point) * 5.0, CORE_INTERACTION_BUFFER_M15_ATR * m15a)
    return _distance(float(s.mid), float(zone.core_low), float(zone.core_high)) <= buffer_price


def primary_zone_interacting(zone: Zone, s: MarketSnapshot) -> bool:
    return _interaction_now(zone, s)


def _build_full_candidate_pool(analysis: Analysis, s: MarketSnapshot):
    existing = {z.zone_id: z for z in analysis.zones}
    context = daily_context(s)
    pool = []
    cmap = {}

    for zid, index, candidate in _candidate_rows(s):
        cmap[zid] = candidate
        zone = existing.get(zid)
        if zone is None:
            zone = build_zone(candidate, s, analysis.liquidity_map, context, index)

        touches = _core_touches(zone, candidate, s)
        zone.touch_count = touches
        _compact_envelope(zone, s)

        parent = candidate.source_tf in H4_PARENT_SOURCES
        has_liq = _resting_liquidity(zone, analysis, s)

        # A single H4 reaction is not the same as accepted invalidation. Revive a
        # parent retired only by legacy touch/envelope logic, then let compact-envelope
        # M15 acceptance decide whether the thesis actually failed.
        if parent and touches <= MAX_PRIMARY_PARENT_REACTIONS and zone.state == ZoneState.RETIRED:
            zone.state = ZoneState.ACTIVE
        zone.state = evaluate_zone_state(zone, s.xau_m15, s.atr_m15)
        if zone.state != ZoneState.ACTIVE:
            continue

        if has_liq:
            conf = set(zone.confluences)
            conf.add("RESTING_LIQUIDITY")
            zone.confluences = sorted(conf)
            zone.independent_confluence_count = len(conf)

        # Raw H4 parents are intentionally B+ in the generic intraday engine. For
        # the primary map, an active H4 parent with resting liquidity and <=1 visit
        # is an A location; M1 still decides whether a paper entry exists.
        if parent and has_liq and touches <= MAX_PRIMARY_PARENT_REACTIONS:
            if zone.grade not in {Grade.A_PLUS, Grade.A}:
                zone.grade = Grade.A
            conf = set(zone.confluences)
            conf.add("H4_PARENT_AUTHORITY")
            if touches == 1:
                conf.add("SINGLE_REACTION_STILL_VALID")
            zone.confluences = sorted(conf)
            zone.independent_confluence_count = len(conf)

        if zone.grade == Grade.REJECT:
            continue
        pool.append(zone)

    return pool, cmap


def apply_two_zone_institutional_map(analysis: Analysis, s: MarketSnapshot) -> list[Zone]:
    """Expose one best institutional SELL and one best institutional BUY zone."""
    if analysis is None:
        return []

    pool, cmap = _build_full_candidate_pool(analysis, s)
    chosen: dict[Direction, Zone] = {}

    for direction in (Direction.BUY, Direction.SELL):
        side = [z for z in pool if z.original_direction == direction]
        if not side:
            continue
        side.sort(
            key=lambda z: _institutional_rank(
                z, analysis, s, cmap.get(z.zone_id)
            )
        )
        zone = side[0]
        if "PRIMARY_INSTITUTIONAL_ZONE" not in zone.notes:
            zone.notes.append("PRIMARY_INSTITUTIONAL_ZONE")
        chosen[direction] = zone

    order = (
        [Direction.SELL, Direction.BUY]
        if analysis.overall_bias == Direction.SELL
        else [Direction.BUY, Direction.SELL]
        if analysis.overall_bias == Direction.BUY
        else [Direction.SELL, Direction.BUY]
    )
    analysis.zones = [chosen[d] for d in order if d in chosen]

    interacting = [z for z in analysis.zones if _interaction_now(z, s)]
    for zone in analysis.zones:
        _replace_readiness(zone, "INTERACTING" if zone in interacting else "ARMED")

    # Keep one primary plan armed even before price reaches it so the journal and
    # MT5 plan are never falsely empty. If either zone is actually interacting,
    # clear the armed selection so the M1_READY handoff can give that touched zone
    # authority on this same analysis pass.
    if interacting:
        analysis.selected_zone_id = ""
    else:
        preferred = chosen.get(analysis.overall_bias)
        if preferred is None and analysis.zones:
            preferred = min(
                analysis.zones,
                key=lambda z: _distance(float(s.mid), float(z.core_low), float(z.core_high)),
            )
        analysis.selected_zone_id = (
            preferred.zone_id
            if preferred is not None
            and preferred.state == ZoneState.ACTIVE
            and preferred.grade in {Grade.A_PLUS, Grade.A}
            else ""
        )

    labels = []
    public = {}
    for z in analysis.zones:
        role = "TREND" if not z.countertrend else "REVERSAL"
        state = _readiness(z)
        labels.append(
            f"{role} {z.original_direction.value}={z.zone_low:.2f}-{z.zone_high:.2f} "
            f"({z.source_tf},{z.grade.value},{state},touches={z.touch_count})"
        )
        public[z.original_direction.value.lower()] = {
            "zone_id": z.zone_id,
            "state": state,
            "source_tf": z.source_tf,
            "grade": z.grade.value,
            "low": z.zone_low,
            "high": z.zone_high,
            "core_low": z.core_low,
            "core_high": z.core_high,
            "touches": z.touch_count,
        }

    summary = "; ".join(labels) if labels else "none"
    analysis.trader_brief = (
        f"D1 context={analysis.overall_bias.value}. Primary institutional map: {summary}. "
        "H4/H4>H1 parent authority, displacement, premium/discount and resting liquidity "
        "outrank proximity. One clean H4 rejection may remain valid; repeated mitigation or "
        "M15 accepted invalidation removes it. M1 sweep/MSS/displacement/value confirmation "
        "remains mandatory."
    )

    policy = dict(analysis.execution_policy or {})
    policy["public_zone_map"] = {
        "map_count": len(analysis.zones),
        "max_zones": 2,
        "one_per_side": True,
        "h4_parent_priority": True,
        "one_clean_h4_reaction_allowed": True,
        "resting_liquidity_qualifies_not_expands": True,
        "core_mitigation_authoritative": True,
        "m15_accepted_invalidation_authoritative": True,
        "m1_confirmation_unchanged": True,
        **public,
    }
    analysis.execution_policy = policy
    return analysis.zones
