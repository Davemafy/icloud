from __future__ import annotations

import re

from .config import SETTINGS
from .engine import _touches, atr
from .intraday_engine import build_candidates
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState


READY_STATES = {"ACTIONABLE", "M1_READY"}


def _readiness(zone: Zone) -> str:
    return zone.core_method.split("|", 1)[0] if "|" in zone.core_method else "WATCH"


def _replace_readiness(zone: Zone, readiness: str) -> None:
    parts = zone.core_method.split("|", 1)
    zone.core_method = readiness if len(parts) == 1 else f"{readiness}|{parts[1]}"


def _distance(mid: float, low: float, high: float) -> float:
    if low <= mid <= high:
        return 0.0
    return low - mid if mid < low else mid - high


def _candidate_map(s: MarketSnapshot):
    out = {}
    for i, c in enumerate(build_candidates(s), 1):
        zid = f"Z_{c.source_tf.replace('>','')}_{c.direction.value}_{i}"
        out[zid] = c
    return out


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

    The newest displayed H4 parent on each side that is still unmitigated at its
    tactical core and still has resting external liquidity on its distal side is
    promoted from WATCH to ACTIONABLE. This changes location qualification only;
    all downstream AI/live-data/M1 confirmation gates remain unchanged.
    """
    if not SETTINGS.paper_only or analysis is None or not analysis.zones:
        return []

    candidates = _candidate_map(s)
    eligible: dict[Direction, list[tuple[int, Zone]]] = {
        Direction.BUY: [],
        Direction.SELL: [],
    }

    for zone in analysis.zones:
        if zone.source_tf != "H4" or zone.state != ZoneState.ACTIVE:
            continue
        candidate = candidates.get(zone.zone_id)
        if candidate is None or candidate.source_tf != "H4":
            continue

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

        eligible[zone.original_direction].append((candidate.source_ts, zone))

    promoted: list[Zone] = []
    for direction in (Direction.BUY, Direction.SELL):
        side = eligible[direction]
        if not side:
            continue
        _, zone = max(side, key=lambda item: item[0])
        _replace_readiness(zone, "ACTIONABLE")
        if zone.grade == Grade.B_PLUS:
            zone.grade = Grade.A
        zone.touch_count = 0
        conf = set(zone.confluences)
        conf.update({"LAST_H4_UNMITIGATED", "RESTING_LIQUIDITY"})
        zone.confluences = sorted(conf)
        zone.independent_confluence_count = len(conf)
        if "H4_LAST_UNMITIGATED_LIQUIDITY_READY" not in zone.notes:
            zone.notes.append("H4_LAST_UNMITIGATED_LIQUIDITY_READY")
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
            "m1_confirmation_unchanged": True,
        }
        analysis.execution_policy = policy
        _refresh_brief_counts(analysis)
        names = ",".join(z.zone_id for z in promoted)
        analysis.trader_brief += f" Latest unmitigated H4 liquidity-qualified: {names}."

    return promoted
