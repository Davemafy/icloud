from __future__ import annotations

import re

from .config import SETTINGS
from .engine import _touches, atr, evaluate_zone_state
from .intraday_engine import _zone as build_zone
from .intraday_engine import build_candidates, daily_context
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState


READY_STATES = {"ACTIONABLE", "M1_READY"}


def _readiness(zone: Zone) -> str:
    return zone.core_method.split("|", 1)[0] if "|" in zone.core_method else "WATCH"


def _replace_readiness(zone: Zone, readiness: str) -> None:
    parts = zone.core_method.split("|", 1)
    zone.core_method = readiness if len(parts) == 1 else f"{readiness}|{parts[1]}"
    zone.notes = [
        f"readiness:{readiness}" if note.startswith("readiness:") else note
        for note in zone.notes
    ]


def _distance(mid: float, low: float, high: float) -> float:
    if low <= mid <= high:
        return 0.0
    return low - mid if mid < low else mid - high


def _zone_id(candidate, index: int) -> str:
    return f"Z_{candidate.source_tf.replace('>','')}_{candidate.direction.value}_{index}"


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


def _refresh_brief_counts(analysis: Analysis) -> None:
    counts = {"ACTIONABLE": 0, "WATCH": 0, "CONTEXT": 0, "M1_READY": 0}
    for z in analysis.zones:
        r = _readiness(z)
        if r in counts:
            counts[r] += 1
    actionable = counts["ACTIONABLE"] + counts["M1_READY"]
    replacement = (
        f"Zones: {actionable} actionable, {counts['WATCH']} watch, "
        f"{counts['CONTEXT']} context."
    )
    if re.search(r"Zones: \d+ actionable, \d+ watch, \d+ context\.", analysis.trader_brief):
        analysis.trader_brief = re.sub(
            r"Zones: \d+ actionable, \d+ watch, \d+ context\.",
            replacement,
            analysis.trader_brief,
            count=1,
        )
    else:
        analysis.trader_brief += " " + replacement


def apply_latest_h4_liquidity_policy(analysis: Analysis, s: MarketSnapshot) -> list[Zone]:
    """Paper-only H4 parent-zone qualification.

    On each side, the newest H4 parent whose tactical core has never been
    mitigated and still has resting external liquidity on its distal side is
    kept in the cloud map and promoted to ACTIONABLE. This changes location
    qualification only; AI/live-data gates and the existing M1 confirmation
    sequence remain unchanged.
    """
    if not SETTINGS.paper_only or analysis is None:
        return []

    existing = {z.zone_id: z for z in analysis.zones}
    eligible: dict[Direction, list[tuple[int, Zone, bool]]] = {
        Direction.BUY: [],
        Direction.SELL: [],
    }
    context = daily_context(s)

    for index, candidate in enumerate(build_candidates(s), 1):
        if candidate.source_tf != "H4":
            continue
        zid = _zone_id(candidate, index)
        zone = existing.get(zid)
        was_displayed = zone is not None
        if zone is None:
            zone = build_zone(candidate, s, analysis.liquidity_map, context, index)

        core_touches = _touches(
            zone.core_low,
            zone.core_high,
            candidate.source_ts,
            s.xau_m15,
        )
        if core_touches != 0:
            continue
        if not _has_resting_liquidity(zone, analysis, s):
            continue

        # The ordinary envelope-touch retirement rule may be wider than the
        # actual tactical core. For this specific H4 rule, core mitigation is
        # authoritative; accepted M15 invalidation still remains authoritative.
        if zone.state == ZoneState.RETIRED:
            zone.state = ZoneState.ACTIVE
        zone.state = evaluate_zone_state(zone, s.xau_m15, s.atr_m15)
        if zone.state != ZoneState.ACTIVE:
            continue

        eligible[zone.original_direction].append(
            (candidate.source_ts, zone, was_displayed)
        )

    promoted: list[Zone] = []
    for direction in (Direction.BUY, Direction.SELL):
        side = eligible[direction]
        if not side:
            continue
        _, zone, was_displayed = max(side, key=lambda item: item[0])
        _replace_readiness(zone, "ACTIONABLE")
        if zone.grade not in (Grade.A_PLUS, Grade.A):
            zone.grade = Grade.A
        zone.touch_count = 0
        conf = set(zone.confluences)
        conf.update({"LAST_H4_UNMITIGATED", "RESTING_LIQUIDITY"})
        zone.confluences = sorted(conf)
        zone.independent_confluence_count = len(conf)
        if "H4_LAST_UNMITIGATED_LIQUIDITY_READY" not in zone.notes:
            zone.notes.append("H4_LAST_UNMITIGATED_LIQUIDITY_READY")
        if not was_displayed:
            analysis.zones.append(zone)
            existing[zone.zone_id] = zone
        promoted.append(zone)

    if promoted and not analysis.selected_zone_id:
        ready = [
            z for z in analysis.zones
            if _readiness(z) in READY_STATES
            and z.state == ZoneState.ACTIVE
            and z.grade in (Grade.A_PLUS, Grade.A)
        ]
        if ready:
            ready.sort(
                key=lambda z: (
                    _distance(s.mid, z.core_low, z.core_high),
                    0 if z.grade == Grade.A_PLUS else 1,
                    -z.location_score,
                )
            )
            analysis.selected_zone_id = ready[0].zone_id

    if promoted:
        policy = dict(analysis.execution_policy or {})
        policy["h4_liquidity_parent_rule"] = {
            "paper_only": True,
            "latest_unmitigated_h4": True,
            "requires_resting_liquidity": True,
            "core_mitigation_authoritative": True,
            "m1_confirmation_unchanged": True,
        }
        analysis.execution_policy = policy
        _refresh_brief_counts(analysis)
        names = ",".join(z.zone_id for z in promoted)
        analysis.trader_brief += f" Latest unmitigated H4 liquidity-qualified: {names}."

    return promoted
