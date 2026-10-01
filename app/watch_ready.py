from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .db import connect
from .engine import atr, evaluate_zone_state
from .models import Analysis, Grade, MarketSnapshot, Zone, ZoneState
from .risk_matrix import execution_grade_eligible
from .zone_reaction_lifecycle import publication_state_for_zone

# Public primary zones stay analysis-only until live price reaches the published
# institutional envelope. M15 validates zone health only; it is not the entry trigger.
# Once the envelope is contacted after publication, Cloud grants M1 SEARCH authority.\n# M1_READY is sticky across re-analysis while the same location/window remains valid;\n# otherwise a successful promotion would demote itself back to WATCH_ONLY on the next cycle.
# Sequence then executes the first-entry model on M1 only:
# liquidity sweep -> micro MSS -> pullback -> closed directional M1 candle.
# Tactical-core contact remains useful location telemetry but is not required.
# A temporary contact window never survives M15 invalidation, deepest-objective
# completion, or age.
MAX_CORE_WIDTH_M15_ATR = 3.00
READY_INPUT_STATES = {"WATCH", "ARMED", "INTERACTING", "M1_READY"}
READY_SOURCE_TFS = {"H1", "H4", "H4>H1"}
THESIS_CONTINUATION_STATUSES = {"REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}
EXECUTION_WINDOW_SECONDS = 3 * 60 * 60
EXECUTION_WINDOW_TARGET_BUFFER_M15_ATR = 0.10
ZONE_CONTACT_LOOKBACK_BARS = 4
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
    """Core handoff requires actual live overlap after this exact geometry was published."""
    publication = publication_state_for_zone(zone)
    published_at = int(publication.get("first_published_at") or 0)
    if published_at <= 0 or int(snapshot.sent_at) < published_at:
        return False
    m15a = _m15_atr(snapshot)
    core_width = max(0.0, float(zone.core_high) - float(zone.core_low))
    if core_width / m15a > MAX_CORE_WIDTH_M15_ATR:
        return False
    lo, hi = sorted((float(zone.core_low), float(zone.core_high)))
    return float(snapshot.ask) >= lo and float(snapshot.bid) <= hi


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


def _execution_touch_limit(zone: Zone) -> int:
    """Compatibility helper: touch count is telemetry only and never limits authority."""
    return 2_147_483_647


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
            # Prefer the execution-owned instance for this exact frozen zone. A
            # pre-zone liquidity or proven zone-sweep handoff may own a derived
            # lifecycle row while the historical base source row is terminal.
            row = db.execute(
                """
                SELECT reaction_key,status,first_seen_at,core_touched_at,reaction_confirmed_at,
                       target1,target2,target3,target1_hit_at,target2_hit_at,target3_hit_at,
                       objective_complete_at,invalidated_at,last_seen_at,best_price,
                       ownership_acquired_at,ownership_authority
                FROM zone_reactions
                WHERE ownership_acquired_at>0 AND ownership_zone_id=?
                  AND invalidated_at=0 AND objective_complete_at=0
                ORDER BY ownership_acquired_at DESC LIMIT 1
                """,
                (zone.zone_id,),
            ).fetchone()
            if row is None:
                row = db.execute(
                    """
                    SELECT reaction_key,status,first_seen_at,core_touched_at,reaction_confirmed_at,
                           target1,target2,target3,target1_hit_at,target2_hit_at,target3_hit_at,
                           objective_complete_at,invalidated_at,last_seen_at,best_price,
                       ownership_acquired_at,ownership_authority
                    FROM zone_reactions WHERE reaction_key=?
                    """,
                    (_reaction_key(zone),),
                ).fetchone()
        return dict(row) if row is not None else {}
    except Exception:
        return {}


def _attached_liquidity(zone: Zone) -> tuple[str, float]:
    for note in zone.notes:
        text = str(note)
        if not text.startswith("attached_liquidity:") or "@" not in text:
            continue
        try:
            head, price_text = text.rsplit("@", 1)
            label = head.split(":", 2)[-1]
            return label, float(price_text)
        except (TypeError, ValueError):
            continue
    return "", 0.0


def _objective_still_open(zone: Zone, snapshot: MarketSnapshot, row: dict[str, Any]) -> tuple[bool, float]:
    """Return the next still-open thesis objective, not only TP1.

    Once TP1 has been reached the thesis may remain OBJECTIVE_IN_PROGRESS and a
    fresh re-entry from the frozen owner location can legitimately target TP2/TP3.
    The old implementation hard-stopped all reaction windows after TP1, which made
    continuation ownership impossible despite the dashboard correctly showing a
    later open objective.
    """
    if str(row.get("status") or "") in TERMINAL_LIFECYCLE_STATES:
        return False, 0.0
    if int(row.get("invalidated_at") or 0) or int(row.get("objective_complete_at") or 0):
        return False, 0.0

    targets = [
        (float(row.get("target1") or zone.original_target1 or 0.0), int(row.get("target1_hit_at") or 0)),
        (float(row.get("target2") or zone.original_target2 or 0.0), int(row.get("target2_hit_at") or 0)),
        (float(row.get("target3") or zone.original_target3 or 0.0), int(row.get("target3_hit_at") or 0)),
    ]
    next_target = next((price for price, hit_at in targets if price > 0 and not hit_at), 0.0)
    if next_target <= 0:
        return False, 0.0

    m15a = _m15_atr(snapshot)
    gap = max(
        float(snapshot.point or 0.01) * max(10.0, float(snapshot.spread_points or 0.0) * 1.5),
        EXECUTION_WINDOW_TARGET_BUFFER_M15_ATR * m15a,
    )
    px = float(snapshot.mid)
    if zone.original_direction.value == "SELL":
        return px > next_target + gap, next_target
    return px < next_target - gap, next_target


def _zone_contact_state(zone: Zone, snapshot: MarketSnapshot) -> dict[str, Any]:
    """Latch a published envelope contact; M1 owns sweep/MSS/entry confirmation."""
    if not _structural_zone_health(zone, snapshot):
        return {}
    if not execution_grade_eligible(zone):
        return {}

    row = _lifecycle_row(zone)
    objective_open, target1 = _objective_still_open(zone, snapshot, row)
    if not objective_open:
        return {}

    publication = publication_state_for_zone(zone)
    published_at = int(publication.get("first_published_at") or 0)
    if published_at <= 0 or int(snapshot.sent_at) < published_at:
        return {}

    now = int(snapshot.sent_at)
    earliest = max(published_at, now - EXECUTION_WINDOW_SECONDS)
    lo, hi = sorted((float(zone.zone_low), float(zone.zone_high)))
    contact_ts = 0
    contact_basis = ""
    contact_price = 0.0

    if float(snapshot.ask) >= lo and float(snapshot.bid) <= hi:
        contact_ts = now
        contact_basis = "LIVE_QUOTE_ENVELOPE_OVERLAP"
        contact_price = float(snapshot.mid)
    else:
        for bar in reversed(list(snapshot.xau_m15)[-ZONE_CONTACT_LOOKBACK_BARS:]):
            if int(bar.ts) < earliest or int(bar.ts) < published_at:
                continue
            if float(bar.high) >= lo and float(bar.low) <= hi:
                contact_ts = int(bar.ts)
                contact_basis = "POST_PUBLICATION_M15_ENVELOPE_OVERLAP"
                contact_price = float(bar.close)
                break

    if contact_ts <= 0:
        return {}

    return {
        "active": True,
        "mode": "LATCHED_AFTER_ZONE_CONTACT",
        "zone_id": zone.zone_id,
        "contact_ts": contact_ts,
        "contact_basis": contact_basis,
        "contact_price": contact_price,
        "age_seconds": max(0, now - contact_ts),
        "expires_at": contact_ts + EXECUTION_WINDOW_SECONDS,
        "target1": target1,
        "target1_open": True,
        "macro_location_latched": True,
        "core_required_for_authority": False,
        "micro_may_complete_outside_core": True,
        "m1_execution_model": "MODEL1_MICRO_SWEEP_MSS_CAUSAL_PD_RETEST_OR_MODEL2_ENGULFING_OR_MODEL3_BREAKOUT_ACCEPTANCE_RETEST",
        "no_chase": True,
    }

def _execution_window_state(zone: Zone, snapshot: MarketSnapshot) -> dict[str, Any]:
    """Return a latched micro-execution window after a real HTF core interaction.

    Macro location is historical once touched. Micro confirmation is allowed to
    complete after price leaves the box, but only while the first planned objective
    is still open and M15 still validates the zone. This prevents a late chase.
    """
    if not _structural_zone_health(zone, snapshot):
        return {}
    if not execution_grade_eligible(zone):
        return {}

    row = _lifecycle_row(zone)
    publication = publication_state_for_zone(zone)
    touched_at = int(publication.get("live_core_touched_at") or 0)
    # Preserve an already-acquired explicit HTF core owner across the V6561
    # migration. This is not a retrospective WATCH touch: ownership_acquired_at
    # proves the old pipeline had already granted deterministic authority.
    if (
        touched_at <= 0
        and int(row.get("ownership_acquired_at") or 0) > 0
        and str(row.get("ownership_authority") or "") == "HTF_CORE_HANDOFF"
        and int(row.get("core_touched_at") or 0) > 0
    ):
        touched_at = int(row.get("core_touched_at") or 0)
    now = int(snapshot.sent_at)
    age = now - touched_at if touched_at else 10**9
    if touched_at <= 0 or age < 0 or age > EXECUTION_WINDOW_SECONDS:
        return {}
    objective_open, target1 = _objective_still_open(zone, snapshot, row)
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
    if not execution_grade_eligible(zone):
        return False
    # A frozen owner keeps the location it actually earned. Core-owned theses can
    # return through the core; zone-contact-owned theses may remain inside their
    # latched contact window while TP1 is still open. Fresh M1 confirmation remains mandatory.
    return bool(
        _common_zone_health(zone, snapshot)
        or _zone_contact_state(zone, snapshot)
        or _execution_window_state(zone, snapshot)
    )


def watch_zone_ready(zone: Zone, snapshot: MarketSnapshot) -> bool:
    """True when a qualified primary has core contact, envelope contact, or a valid latched window."""
    if not SETTINGS.paper_only:
        return False
    if _readiness(zone) not in READY_INPUT_STATES:
        return False
    if not execution_grade_eligible(zone):
        return False
    if _common_zone_health(zone, snapshot):
        return True
    if _zone_contact_state(zone, snapshot):
        return True
    return bool(_execution_window_state(zone, snapshot))


def _mark_ready(analysis: Analysis, selected: Zone, snapshot: MarketSnapshot, thesis_continuation: bool) -> Zone:
    analysis.selected_zone_id = selected.zone_id
    old = str(selected.core_method or "")
    tail = old.split("|", 1)[1] if "|" in old else old

    core_now = _core_ready(selected, snapshot)
    # Preserve the more specific earned core-reaction window before considering
    # a new generic envelope-contact latch. Core remains preference, never a
    # mandatory first-entry gate.
    window = {} if core_now else _execution_window_state(selected, snapshot)
    contact = {} if (core_now or window) else _zone_contact_state(selected, snapshot)
    location_mode = "CORE_NOW" if core_now else str((window or contact).get("mode") or "")
    if location_mode == "LATCHED_AFTER_ZONE_CONTACT":
        tail = f"ZONE_CONTACT_HANDOFF|{tail}" if tail else "ZONE_CONTACT_HANDOFF"
    elif location_mode == "LATCHED_AFTER_CORE_TOUCH":
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
        "active": bool(core_now or contact or window),
        "zone_id": selected.zone_id,
        "mode": location_mode,
        "core_now": core_now,
        "latched": bool(contact or window),
        "core_touched_at": int(snapshot.sent_at if core_now else (window.get("core_touched_at") or 0)),
        "zone_contact_confirmed": bool(contact),
        "contact_ts": int(contact.get("contact_ts") or 0),
        "contact_basis": str(contact.get("contact_basis") or ""),
        "contact_price": float(contact.get("contact_price") or 0.0),
        "sweep_confirmed": False,
        "core_required_for_authority": False if contact else True,
        "expires_at": int((window or contact).get("expires_at") or 0),
        "target1": float((window or contact).get("target1") or selected.original_target1 or 0.0),
        "target1_open": bool((window or contact).get("target1_open", True)),
        "macro_location_latched": bool(contact or window),
        "micro_may_complete_outside_core": bool(contact or window),
        "m1_execution_model": "MODEL1_MICRO_SWEEP_MSS_CAUSAL_PD_RETEST_OR_MODEL2_ENGULFING_OR_MODEL3_BREAKOUT_ACCEPTANCE_RETEST",
        "no_chase": True,
        "paper_only": True,
    }
    analysis.execution_policy = policy

    if thesis_continuation:
        if location_mode == "CORE_NOW":
            location_text = "returned to its surviving institutional location"
        elif location_mode == "LATCHED_AFTER_ZONE_CONTACT":
            location_text = "remains inside its valid post-contact M1 execution window"
        elif location_mode == "LATCHED_AFTER_CORE_TOUCH":
            location_text = "remains inside its valid reaction window"
        else:
            location_text = "retains its previously acquired macro execution location"
        analysis.trader_brief += (
            f" PAPER THESIS_OWNER_CONTINUATION={selected.zone_id}: active {selected.original_direction.value} thesis "
            f"{location_text}. The ownership anchor is not a fresh entry by itself. Sequence now waits for "
            "Model 1 (M1 liquidity sweep -> micro MSS -> fresh OB/FVG -> pullback -> closed directional M1), "
            "Model 2 (closed directional M1 engulfing at/in the valid zone; no separate MSS), or Model 3 "
            "(qualified boundary break -> acceptance -> retest -> closed directional M1; no separate MSS)."
        )
    elif contact:
        analysis.trader_brief += (
            f" PAPER M1_READY={selected.zone_id}: the published institutional envelope was contacted "
            f"({contact.get('contact_basis') or 'ZONE_CONTACT'}). M15 validates zone health only. "
            "M1 execution now has three direct models. Model 1: liquidity sweep -> micro MSS -> fresh "
            "OB/FVG -> pullback -> closed directional M1 candle. Model 2: closed directional M1 engulfing "
            "with valid-zone context, with no separate MSS. Model 3: qualified boundary break -> acceptance -> "
            "retest -> closed directional M1, with no separate MSS. Tactical-core touch, OTE and M15 "
            "sweep/reclaim are not Model 1/2 requirements; Model 3 retains its displacement/retest contract."
        )
    elif window:
        analysis.trader_brief += (
            f" PAPER M1_READY={selected.zone_id}: macro location is already latched. Sequence may use "
            "Model 1 (M1 sweep -> micro MSS -> OB/FVG retest -> closed directional candle), Model 2 "
            "(zone engulfing; no separate MSS), or Model 3 (accepted breakout retest; no separate MSS). "
            "Valid P0/R1/R2 sniper cycles may re-arm while the objective and thesis "
            "risk budget remain open; late chasing remains blocked."
        )
    else:
        analysis.trader_brief += (
            f" PAPER M1_READY={selected.zone_id}: price is interacting with the {selected.source_tf} institutional "
            "location and M15 health is intact. Sequence waits for Model 1 (M1 sweep -> micro MSS -> "
            "OB/FVG retest -> closed directional candle), Model 2 (zone engulfing; no separate MSS), or "
            "Model 3 (qualified breakout -> acceptance -> retest -> closed directional candle; no separate MSS) "
            "before any simulated entry."
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
        if _thesis_continuation_ready(analysis, current, snapshot):
            return _mark_ready(analysis, current, snapshot, thesis_continuation=True)
        if (
            str(thesis.get("status") or "") == "INTERACTING"
            and watch_zone_ready(current, snapshot)
        ):
            return _mark_ready(analysis, current, snapshot, thesis_continuation=False)
        return None

    # With no acquired thesis owner, BOTH independently qualified A/A+ primary
    # sides are allowed to compete for M1 authority. The pre-selected zone is a
    # planning preference (normally D1-aligned), not an execution monopoly.
    # Current executable location comes first; D1 context is retained only as a
    # tie-breaker after location and grade. Once a handoff acquires ownership,
    # the active-thesis branch above remains sticky and blocks the opposite side.
    initial_selected = str(analysis.selected_zone_id or "")
    candidates = [z for z in analysis.zones if watch_zone_ready(z, snapshot)]

    policy = dict(analysis.execution_policy or {})
    competition = {
        "contract": "NO_OWNER_TWO_SIDED_M1_AUTHORITY_V1",
        "mode": "LOCATION_FIRST_D1_TIEBREAK",
        "initial_selected_zone_id": initial_selected,
        "daily_context": analysis.overall_bias.value,
        "ready_candidates": [z.zone_id for z in candidates],
        "winner_zone_id": "",
        "paper_only": True,
    }
    if not candidates:
        policy["m1_authority_competition"] = competition
        analysis.execution_policy = policy
        return None

    def rank(z: Zone) -> tuple:
        envelope_distance = _distance_to_range(
            float(snapshot.mid), float(z.zone_low), float(z.zone_high)
        )
        # Envelope contact grants authority. Core proximity is only the precision
        # tie-breaker when multiple broad envelopes overlap the same quote.
        core_distance = _distance_to_range(
            float(snapshot.mid), float(z.core_low), float(z.core_high)
        )
        grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2}.get(z.grade, 9)
        bias_rank = 0 if z.original_direction == analysis.overall_bias else 1
        tf_rank = 0 if z.source_tf == "H4>H1" else 1 if z.source_tf == "H4" else 2
        return (
            envelope_distance,
            core_distance,
            grade_rank,
            bias_rank,
            tf_rank,
            -float(z.location_score),
        )

    candidates.sort(key=rank)
    winner = candidates[0]
    competition["winner_zone_id"] = winner.zone_id
    competition["winner_direction"] = winner.original_direction.value
    competition["winner_overrode_plan_selection"] = bool(
        initial_selected and initial_selected != winner.zone_id
    )
    policy["m1_authority_competition"] = competition
    analysis.execution_policy = policy
    return _mark_ready(analysis, winner, snapshot, thesis_continuation=False)
