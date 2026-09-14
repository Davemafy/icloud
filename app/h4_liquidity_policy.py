from __future__ import annotations

from .config import SETTINGS
from .engine import _touches, atr, evaluate_zone_state
from .intraday_engine import _zone as build_zone
from .intraday_engine import build_candidates, daily_context
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState


H4_PARENT_SOURCES = {"H4", "H4>H1"}
MAX_VALID_H4_REACTION_EPISODES = 1


def _readiness(zone: Zone) -> str:
    return zone.core_method.split("|", 1)[0] if "|" in zone.core_method else "WATCH"


def _replace_readiness(zone: Zone, readiness: str) -> None:
    parts = zone.core_method.split("|", 1)
    zone.core_method = readiness if len(parts) == 1 else f"{readiness}|{parts[1]}"
    zone.notes = [
        f"readiness:{readiness}" if note.startswith("readiness:") else note
        for note in zone.notes
    ]


def _zone_id(candidate, index: int) -> str:
    return f"Z_{candidate.source_tf.replace('>','')}_{candidate.direction.value}_{index}"


def _parent_ts(candidate) -> int:
    h4 = [int(x.source_ts) for x in candidate.components if str(x.tf) == "H4"]
    return max(h4) if h4 else int(candidate.source_ts)


def _has_resting_liquidity(zone: Zone, analysis: Analysis, s: MarketSnapshot) -> bool:
    h1a = s.atr_h1 or atr(s.xau_h1)
    h4a = atr(s.xau_h4)
    cap = max(1e-9, min(1.50 * h1a, 0.75 * h4a))
    mid = (zone.core_low + zone.core_high) / 2.0
    if zone.original_direction == Direction.SELL:
        return any(
            level.price >= zone.core_high and level.price - mid <= cap
            for level in analysis.liquidity_map
        )
    return any(
        level.price <= zone.core_low and mid - level.price <= cap
        for level in analysis.liquidity_map
    )


def _rank(zone: Zone, candidate, touches: int, s: MarketSnapshot) -> tuple:
    tf_rank = 0 if candidate.source_tf == "H4>H1" else 1
    displacement = 0 if "INSTITUTIONAL_DISPLACEMENT" in zone.confluences else 1
    grade_rank = 0 if zone.grade == Grade.A_PLUS else 1 if zone.grade == Grade.A else 2
    if zone.core_low <= s.mid <= zone.core_high:
        distance = 0.0
    elif s.mid < zone.core_low:
        distance = zone.core_low - s.mid
    else:
        distance = s.mid - zone.core_high
    return (
        touches,
        tf_rank,
        displacement,
        grade_rank,
        -float(zone.location_score),
        distance,
        -_parent_ts(candidate),
    )


def apply_latest_h4_liquidity_policy(analysis: Analysis, s: MarketSnapshot) -> list[Zone]:
    """Keep the strongest still-valid H4 parent on each side in the public pool.

    A single clean reaction does not automatically retire an institutional parent.
    The parent remains qualified while its compact core has no more than one
    interaction episode, resting distal liquidity remains, and M15 has not shown
    accepted invalidation. This is PAPER_ONLY and does not bypass M1 confirmation.
    """
    if not SETTINGS.paper_only or analysis is None:
        return []

    existing = {z.zone_id: z for z in analysis.zones}
    context = daily_context(s)
    eligible: dict[Direction, list[tuple[tuple, Zone, bool, int]]] = {
        Direction.BUY: [],
        Direction.SELL: [],
    }

    for index, candidate in enumerate(build_candidates(s), 1):
        if candidate.source_tf not in H4_PARENT_SOURCES:
            continue
        zid = _zone_id(candidate, index)
        zone = existing.get(zid)
        was_displayed = zone is not None
        if zone is None:
            zone = build_zone(candidate, s, analysis.liquidity_map, context, index)

        touches = _touches(
            zone.core_low,
            zone.core_high,
            candidate.source_ts,
            s.xau_m15,
        )
        if touches > MAX_VALID_H4_REACTION_EPISODES:
            continue
        if not _has_resting_liquidity(zone, analysis, s):
            continue

        # The tactical core and accepted M15 invalidation are authoritative.
        # A prior broad-envelope retirement cannot delete an otherwise-valid H4 core.
        if zone.state == ZoneState.RETIRED and touches <= MAX_VALID_H4_REACTION_EPISODES:
            zone.state = ZoneState.ACTIVE
        zone.state = evaluate_zone_state(zone, s.xau_m15, s.atr_m15)
        if zone.state != ZoneState.ACTIVE:
            continue

        zone.touch_count = touches
        conf = set(zone.confluences)
        conf.update({"H4_PARENT_AUTHORITY", "RESTING_LIQUIDITY"})
        if touches == 1:
            conf.add("SINGLE_REACTION_STILL_VALID")
        zone.confluences = sorted(conf)
        zone.independent_confluence_count = len(conf)
        if zone.grade not in (Grade.A_PLUS, Grade.A):
            zone.grade = Grade.A
        _replace_readiness(zone, "ACTIONABLE")

        eligible[zone.original_direction].append(
            (_rank(zone, candidate, touches, s), zone, was_displayed, touches)
        )

    promoted: list[Zone] = []
    for direction in (Direction.BUY, Direction.SELL):
        side = eligible[direction]
        if not side:
            continue
        _, zone, was_displayed, touches = min(side, key=lambda item: item[0])
        note = (
            "H4_FRESH_RESTING_LIQUIDITY"
            if touches == 0
            else "H4_SINGLE_REACTION_RESTING_LIQUIDITY"
        )
        if note not in zone.notes:
            zone.notes.append(note)
        if not was_displayed:
            analysis.zones.append(zone)
            existing[zone.zone_id] = zone
        promoted.append(zone)

    # Selection is deliberately left to the two-zone interaction handoff. Both
    # parents can stay ARMED while only the zone price is actually touching becomes
    # M1_READY for the existing Sequence EA.
    if promoted:
        policy = dict(analysis.execution_policy or {})
        policy["h4_liquidity_parent_rule"] = {
            "paper_only": True,
            "one_clean_reaction_allowed": True,
            "max_reaction_episodes": MAX_VALID_H4_REACTION_EPISODES,
            "requires_resting_liquidity": True,
            "core_mitigation_authoritative": True,
            "m15_accepted_invalidation_authoritative": True,
            "m1_confirmation_unchanged": True,
        }
        analysis.execution_policy = policy

    return promoted
