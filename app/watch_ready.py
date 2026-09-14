from __future__ import annotations

from .config import SETTINGS
from .engine import atr, evaluate_zone_state
from .models import Analysis, Grade, MarketSnapshot, Zone, ZoneState

# Public primary zones stay ARMED until live price reaches the tactical core.
# M1_READY is still only a PAPER-ONLY handoff into the existing M1 sequence.
CORE_INTERACTION_BUFFER_M15_ATR = 0.30
MAX_CORE_WIDTH_M15_ATR = 3.00
MAX_READY_TOUCHES = 2
READY_INPUT_STATES = {"WATCH", "ARMED", "INTERACTING"}
READY_SOURCE_TFS = {"H1", "H4", "H4>H1"}


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


def watch_zone_ready(zone: Zone, snapshot: MarketSnapshot) -> bool:
    """True when a qualified primary zone is ready for paper M1 monitoring."""
    if not SETTINGS.paper_only:
        return False
    if _readiness(zone) not in READY_INPUT_STATES:
        return False
    if zone.source_tf not in READY_SOURCE_TFS:
        return False
    if zone.grade not in {Grade.A_PLUS, Grade.A}:
        return False
    if int(zone.touch_count) > MAX_READY_TOUCHES:
        return False
    if int(zone.independent_confluence_count) < 2:
        return False
    if float(zone.clear_run) <= 0:
        return False

    state = evaluate_zone_state(zone, snapshot.xau_m15, snapshot.atr_m15)
    if state != ZoneState.ACTIVE:
        return False

    m15a = _m15_atr(snapshot)
    core_width = max(0.0, float(zone.core_high) - float(zone.core_low))
    if core_width / m15a > MAX_CORE_WIDTH_M15_ATR:
        return False

    buffer_price = max(float(snapshot.point) * 5.0, CORE_INTERACTION_BUFFER_M15_ATR * m15a)
    core_distance = _distance_to_range(float(snapshot.mid), float(zone.core_low), float(zone.core_high))
    return core_distance <= buffer_price


def promote_watch_to_m1_ready(analysis: Analysis, snapshot: MarketSnapshot) -> Zone | None:
    """Select the interacting primary zone for PAPER-ONLY M1 monitoring."""
    if not SETTINGS.paper_only:
        return None
    if analysis.selected_zone_id:
        return next((z for z in analysis.zones if z.zone_id == analysis.selected_zone_id), None)

    candidates = [z for z in analysis.zones if watch_zone_ready(z, snapshot)]
    if not candidates:
        return None

    def rank(z: Zone) -> tuple[float, int, float, int]:
        distance = _distance_to_range(float(snapshot.mid), float(z.core_low), float(z.core_high))
        grade_rank = 0 if z.grade == Grade.A_PLUS else 1
        tf_rank = 0 if z.source_tf == "H4>H1" else 1 if z.source_tf == "H4" else 2
        return (distance, grade_rank, tf_rank, -float(z.location_score), int(z.touch_count))

    candidates.sort(key=rank)
    selected = candidates[0]
    analysis.selected_zone_id = selected.zone_id

    old = str(selected.core_method or "")
    tail = old.split("|", 1)[1] if "|" in old else old
    selected.core_method = f"M1_READY|{tail}"
    selected.notes = [
        "readiness:M1_READY",
        *[n for n in selected.notes if not str(n).startswith("readiness:")],
    ]

    analysis.trader_brief += (
        f" PAPER M1_READY={selected.zone_id}: live price is interacting with the "
        f"{selected.source_tf} primary core and M15 health is intact; the existing "
        "M1 sweep/MSS/displacement/value sequence remains required before any simulated entry."
    )
    return selected
