from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .db import connect
from .engine import atr, evaluate_zone_state
from .models import Analysis, Grade, MarketSnapshot, Zone, ZoneState

# Public primary zones stay analysis-only until live price reaches the tactical core.
# Once an A/A+ zone has genuinely interacted, PAPER execution may keep a temporary
# reaction window alive while M1 finishes the micro sequence outside the macro box.
# The window never survives M15 invalidation, TP1 completion, or excessive age.
CORE_INTERACTION_BUFFER_M15_ATR = 0.10
MAX_CORE_WIDTH_M15_ATR = 3.00
MAX_READY_TOUCHES = 1
READY_INPUT_STATES = {"WATCH", "ARMED", "INTERACTING"}
READY_SOURCE_TFS = {"H1", "H4", "H4>H1"}
THESIS_CONTINUATION_STATUSES = {"REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}
EXECUTION_WINDOW_SECONDS = 3 * 60 * 60
EXECUTION_WINDOW_TARGET_BUFFER_M15_ATR = 0.10
TERMINAL_LIFECYCLE_STATES = {"OBJECTIVE_COMPLETE", "INVALIDATED", "INVALIDATED_AFTER_REACTION"}


def _readiness(zone: Zone) -> str:
    method = str(zone.core_method or "")
    return method.split("|", 1)[0] if "|" in method else "WATCH"


def _distance_to_range(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _m15_atr(snapshot: MarketSnapshot) -> float:
    return max(float(snapshot.atr_m15 or atr(snapshot.xau_m15)), float(snapshot.point or 0.01), 1e-9)


def _core_ready(zone: Zone, snapshot: MarketSnapshot) -> bool:
    m15a = _m15_atr(snapshot)
    core_width = max(0.0, float(zone.core_high) - float(zone.core_low))
    if core_width / m15a > MAX_CORE_WIDTH_M15_ATR:
        return False
    buffer_price = max(float(snapshot.point) * 5.0, CORE_INTERACTION_BUFFER_M15_ATR * m15a)
    core_distance = _distance_to_range(float(snapshot.mid), float(zone.core_low), float(zone.core_high))
    return core_distance <= buffer_price


def _structural_zone_health(zone: Zone, snapshot: MarketSnapshot) -> bool:
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
    return bool(state == ZoneState.ACTIVE)


def _common_zone_health(zone: Zone, snapshot: MarketSnapshot) -> bool:
    return bool(_structural_zone_health(zone, snapshot) and _core_ready(zone, snapshot))


def _reaction_key(zone: Zone) -> str:
    source_ts = int(zone.source_ts or 0)
    if source_ts:
        return f"{zone.original_direction.value}|{zone.source_tf}|{source_ts}"
    return (
        f"{zone.original_direction.value}|{zone.source_tf}|0|"
        f"{float(zone.core_low):.2f}|{float(zone.core_high):.2f}"
    )


def _lifecycle_row(zone: Zone) -> dict[str, Any]:
    try:
        with connect() as db:
            row = db.execute(
                """
                SELECT reaction_key,status,core_touched_at,reaction_confirmed_at,
                       target1,target1_hit_at,objective_complete_at,invalidated_at,
                       last_seen_at,best_price
                FROM zone_reactions WHERE reaction_key=?
                """,
                (_reaction_key(zone),),
            ).fetchone()
        return dict(row) if row is not None else {}
    except Exception:
        return {}


def _execution_window_state(zone: Zone, snapshot: MarketSnapshot) -> dict[str, Any]:
    """Return a latched micro-execution window after a real HTF core interaction.

    Macro location is historical once touched. Micro confirmation is allowed to
    complete after price leaves the box, but only while the first planned objective
    is still open and M15 still validates the zone. This prevents a late chase.
    """
    if not _structural_zone_health(zone, snapshot):
        return {}
    if zone.grade not in {Grade.A_PLUS, Grade.A} or int(zone.touch_count) > MAX_READY_TOUCHES:
        return {}

    row = _lifecycle_row(zone)
    touched_at = int(row.get("core_touched_at") or 0)
    now = int(snapshot.sent_at)
    age = now - touched_at if touched_at else 10**9
    if touched_at <= 0 or age < 0 or age > EXECUTION_WINDOW_SECONDS:
        return {}
    if str(row.get("status") or "") in TERMINAL_LIFECYCLE_STATES:
        return {}
    if int(row.get("invalidated_at") or 0) or int(row.get("objective_complete_at") or 0):
        return {}
    if int(row.get("target1_hit_at") or 0):
        return {}

    target1 = float(row.get("target1") or zone.original_target1 or 0.0)
    if target1 <= 0:
        return {}
    m15a = _m15_atr(snapshot)
    gap = max(
        float(snapshot.point or 0.01) * max(10.0, float(snapshot.spread_points or 0.0) * 1.5),
        EXECUTION_WINDOW_TARGET_BUFFER_M15_ATR * m15a,
    )
    px = float(snapshot.mid)
    if zone.original_direction.value == "SELL":
        objective_open = px > target1 + gap
    else:
        objective_open = px < target1 - gap
    if not objective_open:
        return {}

    return {
        "active": True,
        "mode": "LATCHED_AFTER_CORE_TOUCH",
        "zone_id": zone.zone_id,
        "core_touched_at": touched_at,
        "age_seconds": age,
        "expires_at": touched_at + EXECUTION_WINDOW_SECONDS,
        "target1": target1,
        "target1_open": True,
        "macro_location_latched": True,
        "micro_may_complete_outside_core": True,
        "no_chase": True,
    }


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
    # Continuation remains stricter than the first-entry reaction window: a live
    # owner must return to its surviving tactical core before another M1 sequence.
    return _common_zone_health(zone, snapshot)


def watch_zone_ready(zone: Zone, snapshot: MarketSnapshot) -> bool:
    """True when a qualified primary has either live core location or a latched reaction window."""
    if not SETTINGS.paper_only:
        return False
    if _readiness(zone) not in READY_INPUT_STATES:
        return False
    if zone.grade not in {Grade.A_PLUS, Grade.A}:
        return False
    if int(zone.touch_count) > MAX_READY_TOUCHES:
        return False
    if _common_zone_health(zone, snapshot):
        return True
    return bool(_execution_window_state(zone, snapshot))


def _mark_ready(analysis: Analysis, selected: Zone, snapshot: MarketSnapshot, thesis_continuation: bool) -> Zone:
    analysis.selected_zone_id = selected.zone_id
    old = str(selected.core_method or "")
    tail = old.split("|", 1)[1] if "|" in old else old

    core_now = _core_ready(selected, snapshot)
    window = {} if core_now else _execution_window_state(selected, snapshot)
    location_mode = "CORE_NOW" if core_now else str(window.get("mode") or "")
    if location_mode == "LATCHED_AFTER_CORE_TOUCH":
        tail = f"REACTION_WINDOW|{tail}" if tail else "REACTION_WINDOW"
    if thesis_continuation:
        tail = f"THESIS_CONTINUATION|{tail}" if tail else "THESIS_CONTINUATION"
    selected.core_method = f"M1_READY|{tail}"
    selected.notes = [
        "readiness:M1_READY",
        f"execution_location:{location_mode or 'UNKNOWN'}",
        *(["execution_role:THESIS_CONTINUATION"] if thesis_continuation else []),
        *[
            n for n in selected.notes
            if not str(n).startswith("readiness:")
            and not str(n).startswith("execution_role:")
            and not str(n).startswith("execution_location:")
        ],
    ]

    policy = dict(analysis.execution_policy or {})
    policy["execution_window"] = {
        "active": bool(core_now or window),
        "zone_id": selected.zone_id,
        "mode": location_mode,
        "core_now": core_now,
        "latched": bool(window),
        "core_touched_at": int(window.get("core_touched_at") or snapshot.sent_at if core_now else 0),
        "expires_at": int(window.get("expires_at") or 0),
        "target1": float(window.get("target1") or selected.original_target1 or 0.0),
        "target1_open": bool(window.get("target1_open", True)),
        "macro_location_latched": bool(window),
        "micro_may_complete_outside_core": bool(window),
        "no_chase": True,
        "paper_only": True,
    }
    analysis.execution_policy = policy

    if thesis_continuation:
        analysis.trader_brief += (
            f" PAPER M1_READY={selected.zone_id}: active {selected.original_direction.value} thesis "
            "returned to its surviving tactical core. A fresh M1 sequence remains mandatory."
        )
    elif window:
        analysis.trader_brief += (
            f" PAPER M1_READY={selected.zone_id}: macro location was already earned at the qualified core and "
            "is latched as a temporary reaction window. M1 sweep/MSS/displacement/pullback may finish outside "
            "the HTF core while TP1 remains open; late chasing is still blocked."
        )
    else:
        analysis.trader_brief += (
            f" PAPER M1_READY={selected.zone_id}: price is interacting with the {selected.source_tf} primary core, "
            "required structural liquidity is inside the marked zone, and M15 health is intact; M1 confirmation "
            "remains required before any simulated entry."
        )
    return selected


def promote_watch_to_m1_ready(analysis: Analysis, snapshot: MarketSnapshot) -> Zone | None:
    """Select the execution owner for PAPER-ONLY M1 monitoring."""
    if not SETTINGS.paper_only:
        return None

    thesis = _active_thesis(analysis)
    if thesis:
        owner_id = str(thesis.get("owner_zone_id") or "")
        current = next((z for z in analysis.zones if z.zone_id == owner_id), None)
        if current is None:
            return None
        if _readiness(current) == "M1_READY":
            return current
        if _thesis_continuation_ready(analysis, current, snapshot):
            return _mark_ready(analysis, current, snapshot, thesis_continuation=True)
        if str(thesis.get("status") or "") == "INTERACTING" and watch_zone_ready(current, snapshot):
            return _mark_ready(analysis, current, snapshot, thesis_continuation=False)
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
    return _mark_ready(analysis, candidates[0], snapshot, thesis_continuation=False)
