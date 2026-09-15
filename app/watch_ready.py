from __future__ import annotations

from .config import SETTINGS
from .engine import atr, evaluate_zone_state
from .models import Analysis, Grade, MarketSnapshot, Zone, ZoneState

# Public primary zones stay ARMED until live price reaches the tactical core.
# M1_READY is still only a PAPER-ONLY handoff into the existing M1 sequence.
# The wide 300-400 pip envelope is location/sweep context, never an execution
# trigger. Keep the live buffer deliberately small around the tactical core.
CORE_INTERACTION_BUFFER_M15_ATR = 0.10
MAX_CORE_WIDTH_M15_ATR = 3.00
MAX_READY_TOUCHES = 1
READY_INPUT_STATES = {"WATCH", "ARMED", "INTERACTING"}
READY_SOURCE_TFS = {"H1", "H4", "H4>H1"}
THESIS_CONTINUATION_STATUSES = {"REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}


def _readiness(zone: Zone) -> str:
    method = str(zone.core_method or "")
    return method.split("|", 1)[0] if "|" in method else "WATCH"


def _distance_to_range(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _m15_atr(snapshot: MarketSnapshot) -> float:
    return max(float(snapshot.atr_m15 or atr(snapshot.xau_m15)), 1e-9)


def _core_ready(zone: Zone, snapshot: MarketSnapshot) -> bool:
    m15a = _m15_atr(snapshot)
    core_width = max(0.0, float(zone.core_high) - float(zone.core_low))
    if core_width / m15a > MAX_CORE_WIDTH_M15_ATR:
        return False
    buffer_price = max(float(snapshot.point) * 5.0, CORE_INTERACTION_BUFFER_M15_ATR * m15a)
    core_distance = _distance_to_range(float(snapshot.mid), float(zone.core_low), float(zone.core_high))
    return core_distance <= buffer_price


def _common_zone_health(zone: Zone, snapshot: MarketSnapshot) -> bool:
    if zone.source_tf not in READY_SOURCE_TFS:
        return False
    if int(zone.independent_confluence_count) < 2:
        return False
    if float(zone.clear_run) <= 0:
        return False
    if "LIQUIDITY_IN_MARKED_ZONE" not in set(zone.confluences):
        return False
    required = "BSL_IN_MARKED_ZONE" if zone.original_direction.value == "SELL" else "SSL_IN_MARKED_ZONE"
    if required not in set(zone.confluences):
        return False
    state = evaluate_zone_state(zone, snapshot.xau_m15, snapshot.atr_m15)
    return bool(state == ZoneState.ACTIVE and _core_ready(zone, snapshot))


def _active_thesis(analysis: Analysis) -> dict:
    policy = dict(analysis.execution_policy or {})
    meta = dict(policy.get("active_thesis") or {})
    return meta if bool(meta.get("locked")) else {}


def _thesis_continuation_ready(analysis: Analysis, zone: Zone, snapshot: MarketSnapshot) -> bool:
    """Allow same-thesis continuation after a confirmed reaction, never a new opposite thesis."""
    meta = _active_thesis(analysis)
    if not meta:
        return False
    if str(meta.get("owner_zone_id") or "") != zone.zone_id:
        return False
    if str(meta.get("direction") or "") != zone.original_direction.value:
        return False
    if str(meta.get("status") or "") not in THESIS_CONTINUATION_STATUSES:
        return False
    if not bool(meta.get("continuation_authority")):
        return False
    if zone.grade == Grade.REJECT:
        return False
    # Freshness/mitigation may downgrade the current display after the thesis has
    # already reacted. It may not silently reverse ownership. The same surviving
    # geometry still needs structural liquidity, M15 health, core interaction and
    # a new M1 sequence before a simulated continuation entry.
    return _common_zone_health(zone, snapshot)


def watch_zone_ready(zone: Zone, snapshot: MarketSnapshot) -> bool:
    """True when a prompt-qualified new primary zone is ready for paper M1 monitoring."""
    if not SETTINGS.paper_only:
        return False
    if _readiness(zone) not in READY_INPUT_STATES:
        return False
    if zone.grade not in {Grade.A_PLUS, Grade.A}:
        return False
    if int(zone.touch_count) > MAX_READY_TOUCHES:
        return False
    return _common_zone_health(zone, snapshot)


def _mark_ready(analysis: Analysis, selected: Zone, thesis_continuation: bool) -> Zone:
    analysis.selected_zone_id = selected.zone_id
    old = str(selected.core_method or "")
    tail = old.split("|", 1)[1] if "|" in old else old
    if thesis_continuation:
        tail = f"THESIS_CONTINUATION|{tail}" if tail else "THESIS_CONTINUATION"
    selected.core_method = f"M1_READY|{tail}"
    selected.notes = [
        "readiness:M1_READY",
        *( ["execution_role:THESIS_CONTINUATION"] if thesis_continuation else [] ),
        *[
            n for n in selected.notes
            if not str(n).startswith("readiness:")
            and not str(n).startswith("execution_role:")
        ],
    ]

    if thesis_continuation:
        analysis.trader_brief += (
            f" PAPER M1_READY={selected.zone_id}: active {selected.original_direction.value} thesis "
            "is still non-terminal and price has returned to its surviving tactical core. A fresh M1 "
            "sweep/MSS/displacement/value sequence is still mandatory; this is continuation of the "
            "existing thesis, not permission to flip to the opposite map zone."
        )
    else:
        analysis.trader_brief += (
            f" PAPER M1_READY={selected.zone_id}: price is interacting with the "
            f"{selected.source_tf} primary core, required structural liquidity is inside the marked "
            "zone, and M15 health is intact; the existing M1 sweep/MSS/displacement/value sequence "
            "remains required before any simulated entry."
        )
    return selected


def promote_watch_to_m1_ready(analysis: Analysis, snapshot: MarketSnapshot) -> Zone | None:
    """Select the interacting execution owner for PAPER-ONLY M1 monitoring."""
    if not SETTINGS.paper_only:
        return None

    thesis = _active_thesis(analysis)
    if thesis:
        owner_id = str(thesis.get("owner_zone_id") or "")
        current = next((z for z in analysis.zones if z.zone_id == owner_id), None)
        if current is None:
            # Ownership policy already fails closed when the live owner is absent.
            return None
        if _readiness(current) == "M1_READY":
            return current
        if _thesis_continuation_ready(analysis, current, snapshot):
            return _mark_ready(analysis, current, thesis_continuation=True)
        # During initial INTERACTING state, retain normal strict fresh-primary rules.
        if str(thesis.get("status") or "") == "INTERACTING" and watch_zone_ready(current, snapshot):
            return _mark_ready(analysis, current, thesis_continuation=False)
        # A live thesis blocks all opposite-side M1 authority while it remains open.
        return None

    if analysis.selected_zone_id:
        current = next((z for z in analysis.zones if z.zone_id == analysis.selected_zone_id), None)
        if current is not None and _readiness(current) == "M1_READY":
            return current
        if current is None or not watch_zone_ready(current, snapshot):
            return None
        candidates = [current]
    else:
        candidates = [z for z in analysis.zones if watch_zone_ready(z, snapshot)]

    if not candidates:
        return None

    def rank(z: Zone) -> tuple:
        distance = _distance_to_range(float(snapshot.mid), float(z.core_low), float(z.core_high))
        grade_rank = 0 if z.grade == Grade.A_PLUS else 1
        tf_rank = 0 if z.source_tf == "H4>H1" else 1 if z.source_tf == "H4" else 2
        return (distance, grade_rank, tf_rank, -float(z.location_score), int(z.touch_count))

    candidates.sort(key=rank)
    return _mark_ready(analysis, candidates[0], thesis_continuation=False)
