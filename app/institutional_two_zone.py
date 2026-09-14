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
LIQUIDITY_ATTACH_MAX_M15_ATR = 0.60
LIQUIDITY_EDGE_BUFFER_M15_ATR = 0.10
MAX_MARKED_ZONE_WIDTH_M15_ATR = 3.00
H4_PARENT_SOURCES = {"H4", "H4>H1"}
MAX_PRIMARY_TOUCHES = 1


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


def _liquidity_kind(level) -> str:
    label = str(getattr(level, "label", "") or "").upper()
    if "BSL" in label:
        return "BSL"
    if "SSL" in label:
        return "SSL"
    return ""


def _required_liquidity_kind(direction: Direction) -> str:
    return "BSL" if direction == Direction.SELL else "SSL"


def _attached_liquidity(zone: Zone, analysis: Analysis, s: MarketSnapshot):
    """Return the required BSL/SSL only when it belongs to the marked zone area.

    SELL requires BSL in/at the upper half of the source area.
    BUY requires SSL in/at the lower half of the source area.
    A distant liquidity pool is a target/reference, not zone qualification.
    """
    m15a = max(float(s.atr_m15 or atr(s.xau_m15)), 1e-9)
    attach = LIQUIDITY_ATTACH_MAX_M15_ATR * m15a
    edge_tol = LIQUIDITY_EDGE_BUFFER_M15_ATR * m15a
    lo, hi = sorted((float(zone.core_low), float(zone.core_high)))
    mid = (lo + hi) / 2.0
    required = _required_liquidity_kind(zone.original_direction)

    levels = []
    for level in analysis.liquidity_map:
        if _liquidity_kind(level) != required:
            continue
        p = float(level.price)
        if zone.original_direction == Direction.SELL:
            if p < mid - edge_tol or p > hi + attach:
                continue
            distance = abs(p - hi)
        else:
            if p > mid + edge_tol or p < lo - attach:
                continue
            distance = abs(p - lo)
        levels.append((distance, level))

    if not levels:
        return None
    levels.sort(key=lambda row: row[0])
    return levels[0][1]


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
    """Create a compact source-candle envelope before liquidity attachment."""
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
        "M15 accepted body beyond prompt-guided institutional envelope: one >=60% body "
        "and >=0.40 ATR, or two closes each >=0.20 ATR. Wick-only does not invalidate."
    )
    zone.notes = [
        note for note in zone.notes
        if not str(note).startswith("m15_min_width_expansion:")
        and not str(note).startswith("distal_liquidity:")
    ]


def _attach_liquidity_to_marked_zone(zone: Zone, level, s: MarketSnapshot) -> bool:
    """Include only the nearby required BSL/SSL in the marked area."""
    m15a = max(float(s.atr_m15 or atr(s.xau_m15)), 1e-9)
    buffer_price = LIQUIDITY_EDGE_BUFFER_M15_ATR * m15a
    p = float(level.price)
    low = min(float(zone.zone_low), p - buffer_price)
    high = max(float(zone.zone_high), p + buffer_price)
    if high - low > MAX_MARKED_ZONE_WIDTH_M15_ATR * m15a:
        return False

    zone.zone_low = round(low, 5)
    zone.zone_high = round(high, 5)
    zone.invalidation_level = round(
        zone.zone_high if zone.original_direction == Direction.SELL else zone.zone_low,
        5,
    )
    kind = _required_liquidity_kind(zone.original_direction)
    conf = set(zone.confluences)
    conf.update({"LIQUIDITY_IN_MARKED_ZONE", f"{kind}_IN_MARKED_ZONE"})
    zone.confluences = sorted(conf)
    zone.independent_confluence_count = len(conf)
    zone.notes = [
        n for n in zone.notes
        if not str(n).startswith("attached_liquidity:")
    ]
    zone.notes.append(
        f"attached_liquidity:{kind}:{level.label}@{float(level.price):.5f}"
    )
    return True


def _institutional_rank(zone: Zone, analysis: Analysis, s: MarketSnapshot, candidate) -> tuple:
    touches = int(zone.touch_count)
    parent = zone.source_tf in H4_PARENT_SOURCES
    strength = _max_strength(candidate)
    displaced = "INSTITUTIONAL_DISPLACEMENT" in zone.confluences or strength >= 2.0
    has_fvg = "HISTORICAL_DISPLACEMENT_FVG" in zone.confluences

    if zone.source_tf == "H4>H1" and touches == 0:
        tier = 0
    elif zone.source_tf == "H4" and touches == 0:
        tier = 1
    elif parent and touches == 1:
        tier = 2
    elif zone.source_tf == "H1" and touches == 0:
        tier = 3
    elif zone.source_tf == "H1" and touches == 1:
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
        0 if has_fvg else 1,
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
    if int(zone.touch_count) > MAX_PRIMARY_TOUCHES:
        return False
    if "LIQUIDITY_IN_MARKED_ZONE" not in set(zone.confluences):
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
        if touches > MAX_PRIMARY_TOUCHES:
            continue

        _compact_envelope(zone, s)
        attached = _attached_liquidity(zone, analysis, s)
        if attached is None:
            continue
        if not _attach_liquidity_to_marked_zone(zone, attached, s):
            continue

        if zone.state == ZoneState.RETIRED and touches <= MAX_PRIMARY_TOUCHES:
            zone.state = ZoneState.ACTIVE
        zone.state = evaluate_zone_state(zone, s.xau_m15, s.atr_m15)
        if zone.state != ZoneState.ACTIVE:
            continue

        strength = _max_strength(candidate)
        displaced = "INSTITUTIONAL_DISPLACEMENT" in zone.confluences or strength >= 2.0
        if not displaced:
            continue

        if (
            candidate.source_tf in H4_PARENT_SOURCES
            and zone.grade not in {Grade.A_PLUS, Grade.A}
        ):
            zone.grade = Grade.A

        if zone.grade not in {Grade.A_PLUS, Grade.A}:
            continue

        conf = set(zone.confluences)
        conf.add("PROMPT_GUIDED_PRIMARY_ZONE")
        if candidate.source_tf in H4_PARENT_SOURCES:
            conf.add("H4_PARENT_AUTHORITY")
        if touches == 1:
            conf.add("SINGLE_REACTION_STILL_VALID")
        zone.confluences = sorted(conf)
        zone.independent_confluence_count = len(conf)
        pool.append(zone)

    return pool, cmap


def apply_two_zone_institutional_map(analysis: Analysis, s: MarketSnapshot) -> list[Zone]:
    """Expose one prompt-guided institutional SELL and one BUY zone."""
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
        kind = _required_liquidity_kind(z.original_direction)
        attached_note = next(
            (n for n in z.notes if str(n).startswith("attached_liquidity:")),
            "",
        )
        labels.append(
            f"{role} {z.original_direction.value}={z.zone_low:.2f}-{z.zone_high:.2f} "
            f"({z.source_tf},{z.grade.value},{state},touches={z.touch_count},{kind}=IN_ZONE)"
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
            "required_liquidity": kind,
            "liquidity_in_zone": True,
            "attached_liquidity": attached_note,
        }

    summary = "; ".join(labels) if labels else "none"
    analysis.trader_brief = (
        f"D1 context={analysis.overall_bias.value}. Prompt-guided primary map: {summary}. "
        "SELL requires BSL inside the marked zone; BUY requires SSL inside the marked zone. "
        "H4/H4>H1 parent authority, displacement, premium/discount and FVG quality outrank "
        "mere proximity. More than one core mitigation rejects the primary zone. "
        "M15 accepted invalidation removes it. M1 sweep/MSS/displacement/value confirmation "
        "remains mandatory."
    )

    policy = dict(analysis.execution_policy or {})
    policy["public_zone_map"] = {
        "map_count": len(analysis.zones),
        "max_zones": 2,
        "one_per_side": True,
        "sell_requires_bsl_in_marked_zone": True,
        "buy_requires_ssl_in_marked_zone": True,
        "max_primary_touches": MAX_PRIMARY_TOUCHES,
        "h4_parent_priority": True,
        "resting_liquidity_must_be_attached": True,
        "distant_liquidity_is_target_not_zone_qualification": True,
        "compact_zone_required": True,
        "m15_accepted_invalidation_authoritative": True,
        "m1_confirmation_unchanged": True,
        **public,
    }
    analysis.execution_policy = policy
    return analysis.zones
