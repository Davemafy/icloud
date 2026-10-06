from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .db import audit, connect, latest_heartbeats
from .execution_ownership_migration import ensure_execution_ownership_schema
from .models import Analysis, Direction, MarketSnapshot, Zone, ZoneState
from .liquidity_reversal_handoff import INTERZONE_TRANSIT_REASON, interzone_transit_guard
from .liquidity_objective_policy import opposing_zone_front_run_cap
from .risk_matrix import execution_grade_eligible, original_risk_pct, zone_risk_context

THESIS_OWNERSHIP_CONTRACT = "INSTITUTIONAL_THESIS_OWNERSHIP_V65139"
ACTIVE_THESIS_STATUSES = {"INTERACTING", "REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}
CONTINUATION_STATUSES = {"REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}
EXECUTION_AUTHORITIES = {"HTF_CORE_HANDOFF", "HTF_ZONE_CONTACT_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF", "LIQUIDITY_REVERSAL_HANDOFF"}
OWNER_REFRESH_BUFFER_M15_ATR = 0.30
OWNER_M1_HANDOFF_BUFFER_M15_ATR = 0.10
OWNER_MIN_BUFFER_POINTS = 5.0
SEQUENCE_HEARTBEAT_MAX_AGE_SECONDS = 45
LEGACY_OWNER_RELEASE_REASON = "CONTEXT_GRADE_V2_INELIGIBLE_OWNER_FLAT"
INTERZONE_OWNER_RELEASE_REASON = "PREZONE_LIQUIDITY_OWNER_RELEASED_FOR_INTERZONE_TRANSIT"
OWNER_OBJECTIVE_CAP_REASON = "ACTIVE_OPPOSING_PRIMARY_FRONT_RUN"
TERMINAL_FLAT_OWNER_RELEASE_REASON = "TERMINAL_FLAT_CAMPAIGN_ENTRY_CAP_EXHAUSTED"
LATE_STAGE_REACQUISITION_TARGET_COUNT = 2
LATE_STAGE_REACQUISITION_CONTRACT = "CURRENT_HTF_LOCATION_REACQUISITION_V65133"

_AI_RULE = """
13. ACTIVE THESIS OWNERSHIP (PAPER/DEMO): zone interaction by itself never owns execution.
    A thesis may lock execution direction only after an explicit deterministic execution handoff has
    been acquired: HTF_CORE_HANDOFF, HTF_ZONE_CONTACT_HANDOFF, legacy HTF_ZONE_SWEEP_HANDOFF,
    or LIQUIDITY_REVERSAL_HANDOFF. A published envelope contact may arm the primary M1 search;
    it is not itself a trade entry. A+, A and B+ are execution grades; B+ uses the reduced 0.100% base risk and still
    requires every normal M15/M1/AI/safety gate. Touch/mitigation telemetry never removes ownership eligibility. Once an eligible qualified handoff has acquired ownership, that
    thesis remains sticky until M15 accepted invalidation, the deepest effective liquidity objective
    completes, or Sequence proves the exact owner campaign is flat and has exhausted P0/R1/R2.
    Terminal-flat release removes execution monopoly only; it does not falsify objective completion or erase thesis audit truth.
    For a flat owner only, a newly qualified active opposing primary may tighten that effective
    destination to the canonical front-run cap while the frozen owner targets remain audit truth. This cap
    never mutates an open position and cannot be completed from price history that predates the cap.
    A newly ranked opposite zone may remain visible as context but cannot steal M1 authority
    from the acquired thesis. Primary execution has three direct M1 models:
    (1) micro-liquidity sweep -> micro MSS -> causal OB/FVG -> bounded retest -> latest closed M1 candle in thesis direction;
    (2) closed directional M1 real-body engulfing with recent valid-zone context, with no separate MSS;
    (3) qualified institutional boundary breakout -> displacement -> acceptance -> retest -> closed directional M1,
        with no separate MSS and no direct breakout-candle chase.
    Those same models may re-arm for R1/R2 while thesis/objective/risk budget remain live. After two owner objectives
    are already completed, historical ownership alone is no longer sufficient for a fresh entry: the CURRENT freshly
    ranked same-direction HTF zone must itself be active/execution-grade and either be live-interacting now or already
    carry a valid M1_READY handoff. The frozen owner remains lifecycle/audit truth; this rule only reacquires fresh entry
    location and never transfers ownership to the new zone. M15 validates zone health and accepted invalidation; OTE is
    not a mandatory Model 1/2 gate and Model 3 keeps its own displacement contract. If an acquired owner disappears from the current map,
    fail closed until lifecycle release or safe requalification.
"""


def install_thesis_ai_contract() -> None:
    """Extend the AI validator with thesis ownership and the current risk contract."""
    from . import ai

    # Normalize legacy risk wording in the base AI prompt before appending the
    # ownership rule. This keeps deterministic Cloud risk and AI validation on
    # one contract without allowing the AI to set or enlarge lot size.
    ai.SYSTEM = ai.SYSTEM.replace(
        "A+, A and B+ are execution grades; B+ uses 0.25% reduced-risk",
        "A+, A and B+ are execution grades; B+ uses 0.100% reduced-risk",
    )
    ai.SYSTEM = ai.SYSTEM.replace(
        "Base thesis risk is TREND A+=1.00%,\n"
        "   TREND A=0.75%, COUNTERTREND A+=0.50%, COUNTERTREND A=0.25%, B+=0.25% of non-compounding validation capital\n"
        "   before entry-share/model multipliers.",
        "The hard DEMO/PAPER thesis campaign cap is 0.30%. Base thesis risk is TREND A+=0.300%,\n"
        "   TREND A=0.225%, COUNTERTREND A+=0.150%, COUNTERTREND A=0.075%, B+=0.100% of non-compounding validation capital\n"
        "   before entry-share/model multipliers. P0/R1/R2 nominal allocations together may not exceed the thesis budget.",
    )

    marker = "13. ACTIVE THESIS OWNERSHIP"
    if marker not in ai.SYSTEM:
        ai.SYSTEM += _AI_RULE

    # ai._payload contains human-readable contract metadata. Wrap it once so
    # external validation receives the same risk ceiling that deterministic
    # sizing already enforces.
    if not getattr(ai, "_tradezone_risk_payload_v65133", False):
        original_payload = ai._payload

        def _payload_with_current_risk_contract(a, s):
            payload = original_payload(a, s)
            rules = dict(payload.get("rules") or {})
            rules.update(
                {
                    "context_grade_risk_contract": (
                        "Hard thesis cap 0.30%; TREND A+=0.300%, TREND A=0.225%, "
                        "COUNTERTREND A+=0.150%, COUNTERTREND A=0.075%, B+=0.100% "
                        "of non-compounding validation capital before entry-share/model multipliers"
                    ),
                    "bplus_role": (
                        "reduced-risk execution grade at 0.100% with all normal "
                        "M15/M1/AI/safety gates"
                    ),
                    "thesis_campaign_risk_cap_pct": 0.30,
                    "campaign_risk_shares": {"P0": 0.60, "R1": 0.30, "R2": 0.10},
                    "late_stage_owner_reacquisition": (
                        "after two completed owner objectives, fresh entries require "
                        "CURRENT same-direction HTF location reacquisition before M1 confirmation"
                    ),
                }
            )
            payload["rules"] = rules
            return payload

        ai._payload = _payload_with_current_risk_contract
        ai._tradezone_risk_payload_v65133 = True


def _zone_reaction_key(zone: Zone) -> str:
    source_ts = int(zone.source_ts or 0)
    if source_ts:
        return f"{zone.original_direction.value}|{zone.source_tf}|{source_ts}"
    return (
        f"{zone.original_direction.value}|{zone.source_tf}|0|"
        f"{float(zone.core_low):.2f}|{float(zone.core_high):.2f}"
    )


def _sequence_campaign_truth(now: int) -> dict[str, Any]:
    """Return fresh Sequence campaign truth used by fail-safe owner release."""
    rows = latest_heartbeats(30)
    hb = next(
        (x for x in rows if str(x.get("ea") or "") == "InstitutionalSMC_SequenceEA"),
        None,
    )
    if hb is None:
        return {"fresh": False}
    hb_ts = int(hb.get("ts") or 0)
    if hb_ts <= 0 or int(now) - hb_ts > SEQUENCE_HEARTBEAT_MAX_AGE_SECONDS:
        return {"fresh": False}
    payload = hb.get("payload") if isinstance(hb.get("payload"), dict) else {}
    details = dict(payload.get("details") or {}) if isinstance(payload, dict) else {}
    try:
        return {
            "fresh": True,
            "open_positions": max(0, int(details.get("open_positions") or 0)),
            "primary_entries": max(0, int(details.get("primary_entries") or 0)),
            "reentries": max(0, int(details.get("reentries") or 0)),
            "opportunity_slot": str(details.get("opportunity_slot") or ""),
            "gate_stage": str(details.get("gate_stage") or "").upper(),
            "gate_reason": str(details.get("gate_reason") or "").upper(),
            "campaign_key": str(details.get("campaign_key") or ""),
        }
    except (TypeError, ValueError):
        return {"fresh": False}


def _sequence_position_truth(now: int) -> tuple[bool, int]:
    """Return (fresh, open_positions) from the live Sequence heartbeat."""
    truth = _sequence_campaign_truth(now)
    if not truth.get("fresh"):
        return False, 0
    return True, int(truth.get("open_positions") or 0)


def _owner_campaign_key(owner: dict[str, Any]) -> str:
    return (
        f"{str(owner.get('direction') or '')}|"
        f"{str(owner.get('source_tf') or '')}|"
        f"{int(owner.get('source_ts') or 0)}|"
        f"{int(owner.get('ownership_acquired_at') or 0)}"
    )


def _release_terminal_flat_campaign(owner: dict[str, Any], now: int) -> bool:
    """Release execution monopoly only after Sequence proves this exact campaign is terminal and flat.

    This intentionally does NOT set objective_complete_at and does NOT invalidate
    the thesis. The lifecycle row remains historical/audit truth, while a campaign
    that has consumed P0/R1/R2 can no longer block unrelated new execution.
    """
    truth = _sequence_campaign_truth(int(now))
    if not truth.get("fresh"):
        return False
    if int(truth.get("open_positions") or 0) != 0:
        return False

    expected = _owner_campaign_key(owner)
    if not expected or str(truth.get("campaign_key") or "") != expected:
        return False

    terminal_gate = (
        str(truth.get("opportunity_slot") or "") == "REENTRY_CAP_REACHED"
        or (
            str(truth.get("gate_stage") or "") == "THESIS"
            and "REENTRY_LIMIT_REACHED" in str(truth.get("gate_reason") or "")
        )
    )
    if not terminal_gate or int(truth.get("primary_entries") or 0) < 1:
        return False

    key = str(owner.get("reaction_key") or "")
    if not key:
        return False
    reason = TERMINAL_FLAT_OWNER_RELEASE_REASON
    with connect() as db:
        cur = db.execute(
            """
            UPDATE zone_reactions
            SET ownership_execution_released_at=?,
                ownership_execution_release_reason=?,
                last_reason=?,last_seen_at=?
            WHERE reaction_key=?
              AND ownership_acquired_at>0
              AND invalidated_at=0
              AND objective_complete_at=0
              AND COALESCE(ownership_execution_released_at,0)=0
            """,
            (
                int(now),
                reason,
                f"EXECUTION_AUTHORITY_RELEASED:{reason}:campaign={expected}:"
                f"P={int(truth.get('primary_entries') or 0)}:"
                f"R={int(truth.get('reentries') or 0)}",
                int(now),
                key,
            ),
        )
        released = int(cur.rowcount or 0) > 0
    if released:
        audit(
            "thesis.execution_owner.released",
            f"reaction_key={key} reason={reason} campaign={expected} "
            f"primary_entries={int(truth.get('primary_entries') or 0)} "
            f"reentries={int(truth.get('reentries') or 0)} objective_preserved=1",
        )
    return released


def _owner_execution_lock_eligible(owner: dict[str, Any]) -> bool:
    """Whether the frozen owner still qualifies to monopolize execution authority."""
    payload = str(owner.get("ownership_zone_payload") or "")
    if payload:
        try:
            zone = Zone.model_validate_json(payload)
            return execution_grade_eligible(zone)
        except Exception:
            # Fall through to the persisted grade only if the frozen payload
            # cannot be decoded. The immutable-grade contract treats A+/A/B+
            # identically for ownership eligibility; risk differs by grade/context.
            pass
    return str(owner.get("grade") or "").upper() in {"A+", "A", "B+"}


def _retire_legacy_owner_execution_lock(owner: dict[str, Any], now: int) -> None:
    """Retire only the execution lock; keep the lifecycle row for audit/history."""
    key = str(owner.get("reaction_key") or "")
    if not key:
        return
    acquired_at = int(owner.get("ownership_acquired_at") or 0)
    authority = str(owner.get("ownership_authority") or "")
    reason = (
        f"EXECUTION_AUTHORITY_RELEASED:{LEGACY_OWNER_RELEASE_REASON}:"
        f"acquired_at={acquired_at}:authority={authority}"
    )
    with connect() as db:
        cur = db.execute(
            """
            UPDATE zone_reactions
            SET ownership_acquired_at=0,last_reason=?,last_seen_at=?
            WHERE reaction_key=? AND ownership_acquired_at>0
              AND invalidated_at=0 AND objective_complete_at=0
            """,
            (reason, int(now), key),
        )
    if cur.rowcount <= 0:
        return
    audit(
        int(now),
        "thesis.execution_owner.released",
        f"reaction_key={key} reason={LEGACY_OWNER_RELEASE_REASON} "
        f"grade={owner.get('grade','')} authority={authority} acquired_at={acquired_at}",
    )


def _owner_acquired_before_destination_zone(owner: dict[str, Any], zone: Zone) -> bool:
    """True when a liquidity-reversal owner was acquired outside the HTF destination."""
    if str(owner.get("ownership_authority") or "") != "LIQUIDITY_REVERSAL_HANDOFF":
        return False
    anchor = float(owner.get("ownership_anchor_price") or 0.0)
    if anchor <= 0:
        return False
    if zone.original_direction == Direction.SELL:
        return anchor < float(zone.zone_low)
    if zone.original_direction == Direction.BUY:
        return anchor > float(zone.zone_high)
    return False


def _release_interzone_prezone_owner(analysis: Analysis, snapshot: MarketSnapshot) -> dict[str, Any] | None:
    """Release a flat pre-zone owner when the current map shows zone-to-zone transit.

    A pre-zone liquidity reversal is optional micro authority. It must never turn a
    higher SELL destination into an already-active SELL thesis while price is still
    travelling up from a lower BUY zone (or the mirrored SELL-to-BUY journey).
    Existing positions are protected: without fresh Sequence truth proving flat,
    the owner remains fail-closed until it can be released safely.
    """
    now = int(snapshot.sent_at)
    owner = _active_owner_row(now)
    if owner is None or str(owner.get("ownership_authority") or "") != "LIQUIDITY_REVERSAL_HANDOFF":
        return None

    owner_zone = _ownership_zone_snapshot(owner)
    if owner_zone is None:
        wanted = str(owner.get("ownership_zone_id") or owner.get("latest_zone_id") or "")
        owner_zone = next((z for z in analysis.zones if wanted and z.zone_id == wanted), None)
    if owner_zone is None:
        owner_zone = next(
            (z for z in analysis.zones if z.original_direction.value == str(owner.get("direction") or "")),
            None,
        )
    if owner_zone is None or not _owner_acquired_before_destination_zone(owner, owner_zone):
        return None

    transit = interzone_transit_guard(analysis, snapshot, owner_zone)
    if not bool(transit.get("blocked")):
        return None

    sequence_fresh, open_positions = _sequence_position_truth(now)
    if not sequence_fresh or open_positions > 0:
        return {
            "released": False,
            "reason": "SEQUENCE_POSITIONS_OPEN" if open_positions > 0 else "SEQUENCE_POSITION_TRUTH_UNAVAILABLE",
            "interzone_transit": transit,
            "owner_zone_id": owner_zone.zone_id,
        }

    key = str(owner.get("reaction_key") or "")
    acquired_at = int(owner.get("ownership_acquired_at") or 0)
    old_authority = str(owner.get("ownership_authority") or "")
    reason = (
        f"EXECUTION_AUTHORITY_RELEASED:{INTERZONE_OWNER_RELEASE_REASON}:"
        f"acquired_at={acquired_at}:authority={old_authority}:"
        f"origin={transit.get('origin_zone_id','')}:destination={owner_zone.zone_id}"
    )
    with connect() as db:
        cur = db.execute(
            """
            UPDATE zone_reactions
            SET ownership_acquired_at=0,last_reason=?,last_seen_at=?
            WHERE reaction_key=? AND ownership_acquired_at>0
              AND invalidated_at=0 AND objective_complete_at=0
            """,
            (reason, now, key),
        )
    if cur.rowcount <= 0:
        return None

    audit(
        now,
        "thesis.execution_owner.released",
        f"reaction_key={key} reason={INTERZONE_OWNER_RELEASE_REASON} "
        f"origin={transit.get('origin_zone_id','')} destination={owner_zone.zone_id} "
        f"authority={old_authority} acquired_at={acquired_at}",
    )
    release = {
        "released": True,
        "reason": INTERZONE_OWNER_RELEASE_REASON,
        "interzone_reason": INTERZONE_TRANSIT_REASON,
        "interzone_transit": transit,
        "owner_zone_id": owner_zone.zone_id,
        "ownership_acquired_at": acquired_at,
        "ownership_authority": old_authority,
    }
    policy = dict(analysis.execution_policy or {})
    policy["interzone_owner_release"] = release
    analysis.execution_policy = policy
    analysis.trader_brief += (
        f" Previous pre-zone {owner_zone.original_direction.value} handoff released safely while flat: "
        f"price is in transit from {transit.get('origin_zone_id') or 'the opposite zone'} toward "
        f"{owner_zone.zone_id}. Destination-zone contact is required before that side can reacquire authority."
    )
    return release


def _active_owner_row(now: int) -> dict[str, Any] | None:
    """Return the oldest still-live thesis that actually acquired execution authority."""
    ensure_execution_ownership_schema()
    cutoff = int(now) - 7 * 24 * 3600
    with connect() as db:
        table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='zone_reactions'"
        ).fetchone()
        if table is None:
            return None
        rows = db.execute(
            """
            SELECT reaction_key,latest_zone_id,direction,source_tf,source_ts,status,
                   core_low,core_high,zone_low,zone_high,grade,core_touched_at,
                   reaction_confirmed_at,target1,target2,target3,target1_hit_at,
                   target2_hit_at,target3_hit_at,objective_complete_at,invalidated_at,
                   best_price,mfe_price,last_reason,first_seen_at,last_seen_at,
                   ownership_acquired_at,ownership_authority,ownership_analysis_id,
                   ownership_anchor_price,ownership_zone_id,ownership_zone_payload,
                   ownership_objective_cap,ownership_objective_cap_zone_id,
                   ownership_objective_cap_set_at,ownership_objective_cap_reached_at,
                   ownership_objective_cap_reason,ownership_execution_released_at,
                   ownership_execution_release_reason
            FROM zone_reactions
            WHERE first_seen_at>=?
              AND ownership_acquired_at>0
              AND invalidated_at=0
              AND objective_complete_at=0
              AND COALESCE(ownership_execution_released_at,0)=0
              AND status IN ('INTERACTING','REACTION_CONFIRMED','OBJECTIVE_IN_PROGRESS')
            ORDER BY ownership_acquired_at ASC, first_seen_at ASC
            """,
            (cutoff,),
        ).fetchall()
    if not rows:
        return None

    sequence_fresh, open_positions = _sequence_position_truth(int(now))
    for raw in rows:
        owner = dict(raw)
        if _release_terminal_flat_campaign(owner, int(now)):
            continue
        if _owner_execution_lock_eligible(owner):
            return owner

        # Compatibility path for genuinely unsupported/undecodable historical
        # owners only. A+, A and B+ valid frozen owners return above and never
        # reach this branch merely because of grade or touch telemetry.
        if not sequence_fresh or open_positions > 0:
            owner["compat_execution_lock_protected"] = True
            owner["compat_execution_lock_reason"] = (
                "SEQUENCE_POSITIONS_OPEN"
                if open_positions > 0
                else "SEQUENCE_POSITION_TRUTH_UNAVAILABLE"
            )
            return owner

        _retire_legacy_owner_execution_lock(owner, int(now))

    return None


def active_owner_snapshot(now: int) -> dict[str, Any] | None:
    """Public read-only owner snapshot for scheduler refresh decisions."""
    if not SETTINGS.paper_only:
        return None
    return _active_owner_row(int(now))


def _owner_core_interaction(
    snapshot: MarketSnapshot,
    atr_fraction: float,
    allowed_statuses: set[str] | None = None,
) -> dict[str, Any] | None:
    owner = active_owner_snapshot(int(snapshot.sent_at))
    if owner is None:
        return None
    if allowed_statuses is not None and str(owner.get("status") or "") not in allowed_statuses:
        return None
    low, high = sorted((float(owner.get("core_low") or 0.0), float(owner.get("core_high") or 0.0)))
    if high <= low:
        return None
    px = float(snapshot.mid)
    if low <= px <= high:
        distance = 0.0
    else:
        distance = low - px if px < low else px - high
    point = max(float(snapshot.point or 0.01), 1e-9)
    m15a = max(float(snapshot.atr_m15 or 0.0), point)
    buffer_price = max(point * OWNER_MIN_BUFFER_POINTS, float(atr_fraction) * m15a)
    return owner if distance <= buffer_price else None


def owner_core_interacting(snapshot: MarketSnapshot) -> dict[str, Any] | None:
    """Broad refresh trigger when an acquired live thesis returns near its tactical core."""
    return _owner_core_interaction(snapshot, OWNER_REFRESH_BUFFER_M15_ATR)


def owner_m1_handoff_interacting(snapshot: MarketSnapshot) -> dict[str, Any] | None:
    """Strict refresh trigger for a confirmed acquired thesis entering M1 handoff range."""
    return _owner_core_interaction(
        snapshot,
        OWNER_M1_HANDOFF_BUFFER_M15_ATR,
        CONTINUATION_STATUSES,
    )


def _matches_owner(zone: Zone, owner: dict[str, Any]) -> bool:
    """Match only the frozen owner identity/geometry, never a newly re-ranked zone."""
    if zone.state != ZoneState.ACTIVE:
        return False
    if zone.original_direction.value != str(owner.get("direction", "")):
        return False

    ownership_zone_id = str(owner.get("ownership_zone_id") or "")
    if ownership_zone_id:
        return zone.zone_id == ownership_zone_id

    # Legacy rows created before the frozen-zone contract may not yet have an
    # ownership_zone_id. Accept the old id only when geometry still matches the
    # persisted lifecycle row; source timestamp alone is no longer sufficient.
    latest_zone_id = str(owner.get("latest_zone_id") or "")
    if latest_zone_id and zone.zone_id == latest_zone_id:
        return True
    source_ts = int(owner.get("source_ts") or 0)
    source_tf = str(owner.get("source_tf") or "")
    tol = 1e-6
    return bool(
        source_ts
        and int(zone.source_ts or 0) == source_ts
        and str(zone.source_tf) == source_tf
        and abs(float(zone.core_low) - float(owner.get("core_low") or 0.0)) <= tol
        and abs(float(zone.core_high) - float(owner.get("core_high") or 0.0)) <= tol
        and abs(float(zone.zone_low) - float(owner.get("zone_low") or 0.0)) <= tol
        and abs(float(zone.zone_high) - float(owner.get("zone_high") or 0.0)) <= tol
    )


def _ownership_zone_snapshot(owner: dict[str, Any]) -> Zone | None:
    """Restore the exact zone that acquired authority.

    ownership_analysis_id points to the analysis that granted the handoff, so old
    rows can be backfilled safely even if latest_zone_id was later re-ranked.
    """
    payload = str(owner.get("ownership_zone_payload") or "")
    if payload:
        try:
            zone = Zone.model_validate_json(payload)
            if zone.state == ZoneState.ACTIVE:
                return zone
        except Exception:
            pass

    analysis_id = str(owner.get("ownership_analysis_id") or "")
    if not analysis_id:
        return None
    try:
        with connect() as db:
            row = db.execute(
                "SELECT payload FROM analyses WHERE analysis_id=? ORDER BY ts DESC LIMIT 1",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        owning_analysis = Analysis.model_validate_json(str(row["payload"]))
        wanted = str(owner.get("ownership_zone_id") or "")
        zone = next(
            (
                z for z in owning_analysis.zones
                if (wanted and z.zone_id == wanted)
                or (not wanted and z.zone_id == owning_analysis.selected_zone_id)
            ),
            None,
        )
        if zone is None:
            return None
        with connect() as db:
            db.execute(
                """
                UPDATE zone_reactions
                SET ownership_zone_id=CASE WHEN ownership_zone_id='' THEN ? ELSE ownership_zone_id END,
                    ownership_zone_payload=CASE WHEN ownership_zone_payload='' THEN ? ELSE ownership_zone_payload END
                WHERE reaction_key=?
                """,
                (zone.zone_id, zone.model_dump_json(), str(owner.get("reaction_key") or "")),
            )
        owner["ownership_zone_id"] = zone.zone_id
        owner["ownership_zone_payload"] = zone.model_dump_json()
        return zone.model_copy(deep=True)
    except Exception:
        return None


def _enrich_legacy_owner_snapshot(
    analysis: Analysis,
    owner: dict[str, Any],
    frozen: Zone | None,
) -> Zone | None:
    """Repair a minimal legacy mirror from the current exact same-source map.

    This path is deliberately narrow: it never changes owner identity, direction,
    source, core, authority, target lifecycle or acquisition time. It only restores
    the rich structural zone fields (setup type, countertrend context, confluences,
    clear-run and exact source envelope) that were lost by an old mirror fallback.
    """
    if frozen is None or str(frozen.core_method or "") != "PERSISTED_OWNER_MIRROR_LEGACY":
        return frozen

    wanted = str(owner.get("ownership_zone_id") or owner.get("latest_zone_id") or "")
    direction = str(owner.get("direction") or "")
    source_tf = str(owner.get("source_tf") or "")
    source_ts = int(owner.get("source_ts") or 0)
    candidate = next(
        (
            z for z in analysis.zones
            if z.zone_id == wanted
            and z.original_direction.value == direction
            and z.state == ZoneState.ACTIVE
            and (not source_tf or z.source_tf == source_tf)
            and (source_ts <= 0 or int(z.source_ts or 0) == source_ts)
            and abs(float(z.core_low) - float(owner.get("core_low") or 0.0)) <= 1e-6
            and abs(float(z.core_high) - float(owner.get("core_high") or 0.0)) <= 1e-6
        ),
        None,
    )
    if candidate is None:
        return frozen

    enriched = candidate.model_copy(deep=True)
    # Target lifecycle belongs to the acquired owner. Structural enrichment must
    # never silently replace objectives already frozen when authority was acquired.
    for attr, key in (
        ("original_target1", "target1"),
        ("original_target2", "target2"),
        ("original_target3", "target3"),
    ):
        value = float(owner.get(key) or 0.0)
        if value > 0:
            setattr(enriched, attr, value)
    enriched.notes = [
        "legacy_owner_enriched_from_exact_same_source_map",
        *[n for n in list(enriched.notes or []) if str(n) != "legacy_owner_enriched_from_exact_same_source_map"],
    ]

    payload = enriched.model_dump_json()
    key = str(owner.get("reaction_key") or "")
    if key:
        with connect() as db:
            db.execute(
                """
                UPDATE zone_reactions
                SET ownership_zone_id=?,ownership_zone_payload=?,last_reason=?
                WHERE reaction_key=? AND ownership_acquired_at>0
                  AND invalidated_at=0 AND objective_complete_at=0
                """,
                (
                    enriched.zone_id,
                    payload,
                    "LEGACY_OWNER_ENRICHED_FROM_EXACT_SAME_SOURCE_MAP",
                    key,
                ),
            )
        owner["ownership_zone_id"] = enriched.zone_id
        owner["ownership_zone_payload"] = payload
        audit(
            int(analysis.generated_at or analysis.snapshot_at or 0),
            "thesis.execution_owner.enriched",
            f"reaction_key={key} zone={enriched.zone_id} setup={enriched.setup_type} "
            f"countertrend={int(bool(enriched.countertrend))}",
        )
    return enriched



def _owner_completed_target_count(owner: dict[str, Any]) -> int:
    return sum(
        1
        for idx in (1, 2, 3)
        if int(owner.get(f"target{idx}_hit_at") or 0) > 0
    )


def _late_stage_reacquisition_state(
    owner: dict[str, Any],
    current_zone: Zone | None,
    snapshot: MarketSnapshot,
) -> dict[str, Any]:
    """Require current HTF location again after the owner has delivered two objectives.

    The owner remains frozen lifecycle truth. This gate answers a different question:
    whether a NEW entry is still justified by a CURRENT same-direction institutional
    location. A live overlap with the current envelope or an already-valid M1_READY
    state is sufficient to reacquire location; neither condition is an order trigger.
    """
    completed = _owner_completed_target_count(owner)
    required = completed >= LATE_STAGE_REACQUISITION_TARGET_COUNT
    state: dict[str, Any] = {
        "contract": LATE_STAGE_REACQUISITION_CONTRACT,
        "required": required,
        "completed_targets": completed,
        "required_after_completed_targets": LATE_STAGE_REACQUISITION_TARGET_COUNT,
        "satisfied": not required,
        "state": "NOT_REQUIRED" if not required else "REQUIRED",
        "current_zone_id": "",
        "current_zone_source_tf": "",
        "current_zone_grade": "",
        "current_zone_state": "",
        "current_zone_core_low": 0.0,
        "current_zone_core_high": 0.0,
        "current_zone_low": 0.0,
        "current_zone_high": 0.0,
        "current_zone_live_interaction": False,
        "current_zone_m1_ready": False,
        "basis": "OWNER_HAS_FEWER_THAN_TWO_COMPLETED_OBJECTIVES" if not required else "NONE",
        "frozen_owner_preserved": True,
        "ownership_transferred": False,
    }
    if not required:
        return state
    if current_zone is None:
        state["state"] = "REQUIRED_NO_CURRENT_SAME_DIRECTION_ZONE"
        state["basis"] = "NO_CURRENT_SAME_DIRECTION_HTF_ZONE"
        return state

    lo, hi = sorted((float(current_zone.zone_low), float(current_zone.zone_high)))
    live_interaction = bool(float(snapshot.ask) >= lo and float(snapshot.bid) <= hi)
    readiness = str(current_zone.core_method or "").split("|", 1)[0]
    m1_ready = readiness == "M1_READY"
    structurally_valid = bool(
        current_zone.state == ZoneState.ACTIVE and execution_grade_eligible(current_zone)
    )
    satisfied = bool(structurally_valid and (live_interaction or m1_ready))

    state.update(
        {
            "satisfied": satisfied,
            "state": "SATISFIED" if satisfied else "REQUIRED_WAITING_FOR_CURRENT_HTF_LOCATION",
            "current_zone_id": current_zone.zone_id,
            "current_zone_source_tf": current_zone.source_tf,
            "current_zone_grade": current_zone.grade.value,
            "current_zone_state": current_zone.state.value,
            "current_zone_core_low": float(current_zone.core_low),
            "current_zone_core_high": float(current_zone.core_high),
            "current_zone_low": float(current_zone.zone_low),
            "current_zone_high": float(current_zone.zone_high),
            "current_zone_live_interaction": live_interaction,
            "current_zone_m1_ready": m1_ready,
            "basis": (
                "CURRENT_HTF_ZONE_LIVE_ENVELOPE_INTERACTION"
                if live_interaction and structurally_valid
                else "CURRENT_HTF_ZONE_VALID_M1_READY"
                if m1_ready and structurally_valid
                else "CURRENT_HTF_ZONE_NOT_REACQUIRED"
            ),
        }
    )
    return state



def _owner_meta(owner: dict[str, Any], owner_zone: Zone | None) -> dict[str, Any]:
    status = str(owner.get("status") or "INTERACTING")
    direction = str(owner.get("direction") or Direction.NEUTRAL.value)
    owner_original_geometry_published_at = 0
    if owner_zone is not None:
        for raw in list(getattr(owner_zone, "notes", []) or []):
            text = str(raw)
            if text.startswith("geometry_published_at:"):
                try:
                    owner_original_geometry_published_at = int(float(text.split(":", 1)[1]))
                except (TypeError, ValueError):
                    owner_original_geometry_published_at = 0
                break
    return {
        "contract": THESIS_OWNERSHIP_CONTRACT,
        "locked": True,
        "direction": direction,
        "status": status,
        "reaction_key": str(owner.get("reaction_key") or ""),
        "source_tf": str(owner.get("source_tf") or ""),
        "source_ts": int(owner.get("source_ts") or 0),
        "owner_zone_id": str(owner.get("ownership_zone_id") or (owner_zone.zone_id if owner_zone is not None else "")),
        "owner_zone_present": owner_zone is not None,
        "ownership_acquired_at": int(owner.get("ownership_acquired_at") or 0),
        "ownership_authority": str(owner.get("ownership_authority") or ""),
        "ownership_analysis_id": str(owner.get("ownership_analysis_id") or ""),
        "ownership_anchor_price": float(owner.get("ownership_anchor_price") or 0.0),
        "reaction_confirmed_at": int(owner.get("reaction_confirmed_at") or 0),
        "core_touched_at": int(owner.get("core_touched_at") or 0),
        "target1_hit_at": int(owner.get("target1_hit_at") or 0),
        "target2_hit_at": int(owner.get("target2_hit_at") or 0),
        "target3_hit_at": int(owner.get("target3_hit_at") or 0),
        "same_direction_execution_only": True,
        "opposite_execution_blocked": True,
        "d1_context_cannot_override_live_thesis": True,
        "current_grade_downgrade_does_not_flip_thesis": True,
        "continuation_authority": status in CONTINUATION_STATUSES,
        "release_conditions": [
            "M15_ACCEPTED_INVALIDATION",
            "DEEPEST_PLANNED_LIQUIDITY_OBJECTIVE_REACHED",
            "OPPOSING_ZONE_OWNER_OBJECTIVE_CAP_REACHED",
            "TERMINAL_FLAT_CAMPAIGN_ENTRY_CAP_EXHAUSTED",
        ],
        "fresh_m1_confirmation_required": True,
        "no_chase": True,
        "objective_open": True,
        "target1": float(owner.get("target1") or 0.0),
        "target2": float(owner.get("target2") or 0.0),
        "target3": float(owner.get("target3") or 0.0),
        "best_price": float(owner.get("best_price") or 0.0),
        "mfe_price": float(owner.get("mfe_price") or 0.0),
        "ownership_objective_cap": float(owner.get("ownership_objective_cap") or 0.0),
        "ownership_objective_cap_zone_id": str(owner.get("ownership_objective_cap_zone_id") or ""),
        "ownership_objective_cap_set_at": int(owner.get("ownership_objective_cap_set_at") or 0),
        "ownership_objective_cap_reached_at": int(owner.get("ownership_objective_cap_reached_at") or 0),
        "ownership_objective_cap_reason": str(owner.get("ownership_objective_cap_reason") or ""),
        "frozen_owner_targets_preserved": True,
        "owner_original_geometry_published_at": owner_original_geometry_published_at,
        "owner_projection": owner_zone is not None,
    }


def _sync_owner_public_map(analysis: Analysis, owner_zone: Zone) -> None:
    """Keep public_zone_map identity/geometry aligned with a frozen thesis owner.

    apply_thesis_ownership may replace a freshly ranked same-side zone with the
    exact zone that originally acquired execution authority. public_zone_map is
    side-keyed and was built before that replacement, so leaving it untouched
    creates two competing zone identities in the same analysis payload. The AI
    validator and dashboard then see stale geometry/mitigation telemetry even
    though analysis.zones correctly contains the owner. This is display/contract
    synchronization only; it never changes the frozen owner geometry or authority.
    """
    policy = dict(analysis.execution_policy or {})
    zone_map = dict(policy.get("public_zone_map") or {})
    side = owner_zone.original_direction.value.lower()
    entry = dict(zone_map.get(side) or {})

    def note_text(prefix: str, fallback: str = "") -> str:
        for raw in list(owner_zone.notes or []):
            text = str(raw)
            if text.startswith(prefix):
                return text.split(":", 1)[1]
        return fallback

    def note_int(prefix: str, fallback: int = 0) -> int:
        raw = note_text(prefix, "")
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return int(fallback)

    def note_float(prefix: str, fallback: float = 0.0) -> float:
        raw = note_text(prefix, "")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(fallback)

    structural_grade = note_text("structural_grade:", owner_zone.grade.value)
    current_grade = note_text("current_execution_grade:", owner_zone.grade.value)
    live_touch = note_int("live_core_touched_at:", 0)
    publication_status = note_text(
        "publication_execution_status:",
        "LIVE_CONTACT_CONFIRMED" if live_touch else "RETEST_ONLY_NO_LIVE_CONTACT",
    )

    # zone_id is intentionally not exported by the cleaned public map because
    # DataBridge treats literal zone_id fields as renderable zone records.
    entry.pop("zone_id", None)
    entry.update(
        {
            "audit_zone_id": owner_zone.zone_id,
            "direction": owner_zone.original_direction.value,
            "flip_direction": owner_zone.flip_direction.value,
            "setup_type": owner_zone.setup_type,
            "state": str(owner_zone.core_method or "").split("|", 1)[0],
            "source_tf": owner_zone.source_tf,
            "source_ts": int(owner_zone.source_ts or 0),
            "structural_grade": structural_grade,
            "grade": current_grade,
            "current_execution_grade": current_grade,
            "grade_degrade_reason": note_text("grade_degrade_reason:", "NONE"),
            "structural_aplus_missing": note_text("structural_aplus_missing:", "NONE"),
            "structural_a_missing": note_text("structural_a_missing:", "NONE"),
            "grade_location_score": note_float(
                "grade_location_score:", float(owner_zone.location_score or 0.0)
            ),
            "grade_source_strength": note_float("grade_source_strength:", 0.0),
            "low": float(owner_zone.zone_low),
            "high": float(owner_zone.zone_high),
            "core_low": float(owner_zone.core_low),
            "core_high": float(owner_zone.core_high),
            "touches": int(owner_zone.touch_count),
            "qualified_mitigations": note_int(
                "qualified_mitigations:", int(owner_zone.touch_count)
            ),
            "raw_core_touch_episodes": note_int(
                "raw_core_touch_episodes:", int(owner_zone.touch_count)
            ),
            "mitigation_audit": dict(owner_zone.mitigation_audit or {}),
            "mitigation_expected_approach_side": str(
                (owner_zone.mitigation_audit or {}).get("expected_approach_side") or ""
            ),
            "mitigation_counting_stopped": bool(
                (owner_zone.mitigation_audit or {}).get("counting_stopped")
            ),
            "confluences": list(owner_zone.confluences or []),
            "execution_grade_eligible": bool(execution_grade_eligible(owner_zone)),
            "risk_context": zone_risk_context(owner_zone),
            "base_risk_pct": float(original_risk_pct(owner_zone)),
            "geometry_published_at": note_int("geometry_published_at:", 0),
            "owner_original_geometry_published_at": note_int("geometry_published_at:", 0),
            "publication_qualified_mitigations": note_int(
                "publication_qualified_mitigations:", 0
            ),
            "publication_raw_core_contacts": note_int(
                "publication_raw_core_contacts:", 0
            ),
            "live_core_touched_at": live_touch,
            "live_core_touch_basis": note_text("live_core_touch_basis:", ""),
            "live_core_touch_price": note_float("live_core_touch_price:", 0.0),
            "publication_execution_status": publication_status,
            "owner_projection": True,
            "owner_projection_contract": "FROZEN_OWNER_PUBLIC_MAP_IDENTITY_V65129",
        }
    )
    zone_map[side] = entry
    zone_map["map_count"] = len(list(analysis.zones or []))
    policy["public_zone_map"] = zone_map
    analysis.execution_policy = policy


def _handoff_reaction_instance(
    db,
    analysis: Analysis,
    snapshot: MarketSnapshot,
    zone: Zone,
    authority: str,
    anchor: float,
) -> tuple[str, Any] | tuple[str, None]:
    """Return a live lifecycle row, creating a fresh handoff instance when safe.

    A remote liquidity-reversal or proven outer-zone sweep can legitimately earn
    execution before the tactical core. If the base source row is historical/
    terminal (or absent because that source was requalified after its old lifecycle
    ended), do not let the stale row poison the new deterministic handoff. Preserve
    the old row and create a new analysis-scoped execution instance instead.

    HTF_CORE_HANDOFF remains strict: it must attach to an existing live lifecycle row.
    """
    base_key = _zone_reaction_key(zone)
    row = db.execute("SELECT * FROM zone_reactions WHERE reaction_key=?", (base_key,)).fetchone()
    terminal = bool(
        row is not None
        and (
            int(row["invalidated_at"] or 0)
            or int(row["objective_complete_at"] or 0)
            or str(row["status"] or "") not in ACTIVE_THESIS_STATUSES | {"ARMED"}
        )
    )
    if row is not None and not terminal:
        return base_key, row

    if authority not in {"LIQUIDITY_REVERSAL_HANDOFF", "HTF_ZONE_CONTACT_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF"}:
        return base_key, None

    instance_key = f"{base_key}|OWN|{analysis.analysis_id}"
    existing = db.execute(
        "SELECT * FROM zone_reactions WHERE reaction_key=?",
        (instance_key,),
    ).fetchone()
    if existing is not None:
        return instance_key, existing

    now = int(snapshot.sent_at)
    preconfirmed_authority = authority in {"LIQUIDITY_REVERSAL_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF"}
    status = "REACTION_CONFIRMED" if preconfirmed_authority else "INTERACTING"
    reaction_confirmed_at = now if preconfirmed_authority else 0
    db.execute(
        """
        INSERT INTO zone_reactions(
            reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
            direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
            first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
            target1,target2,target3,runner,target1_hit_at,target2_hit_at,target3_hit_at,
            objective_complete_at,invalidated_at,best_price,mfe_price,last_reason,
            ownership_acquired_at,ownership_authority,ownership_analysis_id,ownership_anchor_price,
            ownership_zone_id,ownership_zone_payload
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            instance_key, analysis.analysis_id, analysis.analysis_id, zone.zone_id, zone.zone_id,
            zone.original_direction.value, zone.source_tf, int(zone.source_ts or 0),
            float(zone.core_low), float(zone.core_high), float(zone.zone_low), float(zone.zone_high),
            zone.grade.value, status, now, now, 0, reaction_confirmed_at,
            float(zone.original_target1 or 0.0), float(zone.original_target2 or 0.0),
            float(zone.original_target3 or 0.0), float(zone.original_runner or 0.0),
            0, 0, 0, 0, 0, float(anchor), 0.0,
            f"HANDOFF_INSTANCE_CREATED:{authority}",
            0, "", "", 0.0, "", "",
        ),
    )
    created = db.execute(
        "SELECT * FROM zone_reactions WHERE reaction_key=?",
        (instance_key,),
    ).fetchone()
    return instance_key, created


def acquire_execution_ownership(
    analysis: Analysis,
    snapshot: MarketSnapshot,
    authority: str,
    zone_id: str,
    anchor_price: float = 0.0,
) -> dict[str, Any] | None:
    """Persist thesis ownership only after a final approved execution handoff.

    HTF_CORE_HANDOFF originates from tactical-core M1_READY. HTF_ZONE_CONTACT_HANDOFF
    originates from a qualified published-envelope contact and starts as INTERACTING;
    the M1 sequence must still prove the reaction. Legacy HTF_ZONE_SWEEP_HANDOFF keeps
    its historical preconfirmed semantics for persisted owners. LIQUIDITY_REVERSAL_HANDOFF is M15-confirmed before
    the remote context core.
    This function never creates a zone or an order.
    """
    if not SETTINGS.paper_only or authority not in EXECUTION_AUTHORITIES:
        return None
    zone = next((z for z in analysis.zones if z.zone_id == zone_id and z.state == ZoneState.ACTIVE), None)
    if zone is None or not execution_grade_eligible(zone):
        return None

    ensure_execution_ownership_schema()
    now = int(snapshot.sent_at)
    anchor = float(anchor_price or snapshot.mid)
    liquidity_authority = authority == "LIQUIDITY_REVERSAL_HANDOFF"
    zone_contact_authority = authority == "HTF_ZONE_CONTACT_HANDOFF"
    zone_sweep_authority = authority == "HTF_ZONE_SWEEP_HANDOFF"
    preconfirmed_authority = liquidity_authority or zone_sweep_authority
    with connect() as db:
        key, row = _handoff_reaction_instance(db, analysis, snapshot, zone, authority, anchor)
        if row is None:
            return None
        if (
            int(row["invalidated_at"] or 0)
            or int(row["objective_complete_at"] or 0)
            or int(row["ownership_execution_released_at"] or 0)
        ):
            return None
        status = str(row["status"] or "ARMED")
        if status not in ACTIVE_THESIS_STATUSES and not (
            (liquidity_authority or zone_contact_authority or zone_sweep_authority) and status == "ARMED"
        ):
            return None

        db.execute(
            """
            UPDATE zone_reactions SET
                ownership_acquired_at=CASE WHEN ownership_acquired_at=0 THEN ? ELSE ownership_acquired_at END,
                ownership_authority=CASE WHEN ownership_acquired_at=0 OR ownership_authority='' THEN ? ELSE ownership_authority END,
                ownership_analysis_id=CASE WHEN ownership_acquired_at=0 OR ownership_analysis_id='' THEN ? ELSE ownership_analysis_id END,
                ownership_anchor_price=CASE WHEN ownership_acquired_at=0 OR ownership_anchor_price<=0 THEN ? ELSE ownership_anchor_price END,
                ownership_zone_id=CASE WHEN ownership_acquired_at=0 OR ownership_zone_id='' THEN ? ELSE ownership_zone_id END,
                ownership_zone_payload=CASE WHEN ownership_acquired_at=0 OR ownership_zone_payload='' THEN ? ELSE ownership_zone_payload END,
                reaction_confirmed_at=CASE WHEN ?=1 AND reaction_confirmed_at=0 THEN ? ELSE reaction_confirmed_at END,
                status=CASE
                    WHEN ?=1 AND status IN ('ARMED','INTERACTING') THEN 'REACTION_CONFIRMED'
                    ELSE status
                END,
                last_reason=?,last_seen_at=?
            WHERE reaction_key=?
            """,
            (
                now, authority, analysis.analysis_id, anchor, zone.zone_id, zone.model_dump_json(),
                1 if preconfirmed_authority else 0, now,
                1 if preconfirmed_authority else 0,
                f"EXECUTION_AUTHORITY_ACQUIRED:{authority}", now, key,
            ),
        )
        refreshed = db.execute("SELECT * FROM zone_reactions WHERE reaction_key=?", (key,)).fetchone()
    if refreshed is None:
        return None
    owner = dict(refreshed)
    policy = dict(analysis.execution_policy or {})
    policy["active_thesis"] = _owner_meta(owner, zone)
    analysis.execution_policy = policy
    zone.notes = [
        f"thesis_owner:{zone.original_direction.value}:{owner.get('status','INTERACTING')}",
        *[n for n in zone.notes if not str(n).startswith("thesis_owner:")],
    ]
    # Do not bake a point-in-time "ownership acquired" statement into the long
    # institutional brief. The persisted row is audit truth, while active_thesis is
    # the authoritative CURRENT lock state and may legitimately release later.
    return owner


def _owner_live_targets(owner: dict[str, Any]) -> list[float]:
    """Return frozen owner targets that were genuinely ahead at ownership."""
    direction = str(owner.get("direction") or "")
    anchor = float(owner.get("ownership_anchor_price") or 0.0)
    values = [
        float(owner.get("target1") or 0.0),
        float(owner.get("target2") or 0.0),
        float(owner.get("target3") or 0.0),
    ]
    if anchor <= 0:
        return [x for x in values if x > 0]
    if direction == Direction.BUY.value:
        return [x for x in values if x > anchor]
    if direction == Direction.SELL.value:
        return [x for x in values if 0 < x < anchor]
    return []


def _cap_is_ahead_of_flat_market(direction: str, cap: float, snapshot: MarketSnapshot) -> bool:
    """A flat-owner lifecycle cap must be reachable ahead of the current executable quote.

    The ownership anchor belongs to the historical handoff and may sit beyond the
    new opposing-zone cap after price has retraced. With zero open positions there
    is no live trade whose profit must be measured from that old anchor. Requiring
    the cap to stay beyond the historical anchor would therefore preserve exactly
    the stale lock this reconciliation is intended to remove.
    """
    if cap <= 0:
        return False
    point = max(abs(float(snapshot.point or 0.01)), 1e-9)
    gap = max(point * 5.0, point * float(snapshot.spread_points or 0.0) * 1.50)
    if direction == Direction.BUY.value:
        return cap > float(snapshot.ask) + gap
    if direction == Direction.SELL.value:
        return cap < float(snapshot.bid) - gap
    return False


def _cap_is_stricter(direction: str, candidate: float, current: float) -> bool:
    """True when candidate is closer to the owner anchor in the profit direction."""
    if current <= 0:
        return True
    if direction == Direction.BUY.value:
        return candidate < current - 1e-9
    if direction == Direction.SELL.value:
        return candidate > current + 1e-9
    return False


def _cap_blocks_deepest(direction: str, cap: float, deepest: float) -> bool:
    if cap <= 0 or deepest <= 0:
        return False
    if direction == Direction.BUY.value:
        return cap < deepest - 1e-9
    if direction == Direction.SELL.value:
        return cap > deepest + 1e-9
    return False


def _reconcile_owner_objective_cap(
    analysis: Analysis,
    snapshot: MarketSnapshot,
    owner: dict[str, Any],
    owner_zone: Zone | None,
) -> None:
    """Tighten a flat owner's lifecycle destination in front of a new opposite primary.

    The frozen owner zone and original target ladder remain immutable audit truth.
    This adds a one-way lifecycle/execution cap only when Sequence proves there are
    no open positions. It never opens, closes, flips, or modifies a live position.
    """
    policy = dict(analysis.execution_policy or {})
    existing = float(owner.get("ownership_objective_cap") or 0.0)
    existing_zone_id = str(owner.get("ownership_objective_cap_zone_id") or "")
    existing_set_at = int(owner.get("ownership_objective_cap_set_at") or 0)

    if owner_zone is None:
        policy["owner_objective_cap_reconciliation"] = {
            "state": "OWNER_ZONE_UNAVAILABLE",
            "active_cap": existing,
            "opposing_zone_id": existing_zone_id,
            "frozen_targets_preserved": True,
            "live_position_targets_mutated": False,
        }
        analysis.execution_policy = policy
        return

    candidate, cap_meta = opposing_zone_front_run_cap(owner_zone, analysis, snapshot)
    if candidate is None or cap_meta is None:
        policy["owner_objective_cap_reconciliation"] = {
            "state": "ACTIVE_CAP_PRESERVED" if existing > 0 else "NO_OPPOSING_CAP_REQUIRED",
            "active_cap": existing,
            "opposing_zone_id": existing_zone_id,
            "frozen_targets_preserved": True,
            "live_position_targets_mutated": False,
        }
        analysis.execution_policy = policy
        return

    direction = str(owner.get("direction") or owner_zone.original_direction.value)
    anchor = float(owner.get("ownership_anchor_price") or 0.0)
    live_targets = _owner_live_targets(owner)
    deepest = live_targets[-1] if live_targets else 0.0
    proposed = float(candidate)
    ahead_of_market = _cap_is_ahead_of_flat_market(direction, proposed, snapshot)

    eligible = bool(
        deepest > 0
        and ahead_of_market
        and _cap_blocks_deepest(direction, proposed, deepest)
        and _cap_is_stricter(direction, proposed, existing)
    )
    if not eligible:
        policy["owner_objective_cap_reconciliation"] = {
            "state": "ACTIVE_CAP_PRESERVED" if existing > 0 else "NO_STRICTER_CAP_REQUIRED",
            "active_cap": existing,
            "opposing_zone_id": existing_zone_id,
            "candidate_cap": round(proposed, 5),
            "candidate_zone_id": str(cap_meta.get("zone_id") or ""),
            "frozen_deepest_target": round(deepest, 5),
            "ownership_anchor_price": round(anchor, 5),
            "current_market_reference": round(float(snapshot.ask if direction == Direction.BUY.value else snapshot.bid), 5),
            "candidate_ahead_of_current_flat_market": ahead_of_market,
            "cap_reference_basis": "CURRENT_FLAT_EXECUTABLE_QUOTE_NOT_HISTORICAL_OWNERSHIP_ANCHOR",
            "frozen_targets_preserved": True,
            "live_position_targets_mutated": False,
        }
        analysis.execution_policy = policy
        return

    sequence_fresh, open_positions = _sequence_position_truth(int(snapshot.sent_at))
    if not sequence_fresh or open_positions > 0:
        policy["owner_objective_cap_reconciliation"] = {
            "state": "DEFERRED_OPEN_POSITIONS" if open_positions > 0 else "DEFERRED_SEQUENCE_TRUTH_UNAVAILABLE",
            "active_cap": existing,
            "candidate_cap": round(proposed, 5),
            "candidate_zone_id": str(cap_meta.get("zone_id") or ""),
            "frozen_deepest_target": round(deepest, 5),
            "ownership_anchor_price": round(anchor, 5),
            "current_market_reference": round(float(snapshot.ask if direction == Direction.BUY.value else snapshot.bid), 5),
            "cap_reference_basis": "CURRENT_FLAT_EXECUTABLE_QUOTE_NOT_HISTORICAL_OWNERSHIP_ANCHOR",
            "sequence_fresh": sequence_fresh,
            "open_positions": open_positions,
            "frozen_targets_preserved": True,
            "live_position_targets_mutated": False,
        }
        analysis.execution_policy = policy
        return

    key = str(owner.get("reaction_key") or "")
    if not key:
        return

    now = int(snapshot.sent_at)
    opposing_zone_id = str(cap_meta.get("zone_id") or "")
    with connect() as db:
        cur = db.execute(
            """
            UPDATE zone_reactions
            SET ownership_objective_cap=?,
                ownership_objective_cap_zone_id=?,
                ownership_objective_cap_set_at=?,
                ownership_objective_cap_reached_at=0,
                ownership_objective_cap_reason=?
            WHERE reaction_key=? AND ownership_acquired_at>0
              AND invalidated_at=0 AND objective_complete_at=0
            """,
            (proposed, opposing_zone_id, now, OWNER_OBJECTIVE_CAP_REASON, key),
        )
    if cur.rowcount <= 0:
        return

    owner["ownership_objective_cap"] = proposed
    owner["ownership_objective_cap_zone_id"] = opposing_zone_id
    owner["ownership_objective_cap_set_at"] = now
    owner["ownership_objective_cap_reached_at"] = 0
    owner["ownership_objective_cap_reason"] = OWNER_OBJECTIVE_CAP_REASON

    policy = dict(analysis.execution_policy or {})
    policy["active_thesis"] = _owner_meta(owner, owner_zone)
    policy["owner_objective_cap_reconciliation"] = {
        "state": "APPLIED",
        "active_cap": round(proposed, 5),
        "opposing_zone_id": opposing_zone_id,
        "frozen_deepest_target": round(deepest, 5),
        "ownership_anchor_price": round(anchor, 5),
        "current_market_reference": round(float(snapshot.ask if direction == Direction.BUY.value else snapshot.bid), 5),
        "cap_reference_basis": "CURRENT_FLAT_EXECUTABLE_QUOTE_NOT_HISTORICAL_OWNERSHIP_ANCHOR",
        "previous_cap": round(existing, 5) if existing > 0 else 0.0,
        "previous_cap_set_at": existing_set_at,
        "sequence_fresh": True,
        "open_positions": 0,
        "frozen_targets_preserved": True,
        "live_position_targets_mutated": False,
        "fresh_m1_confirmation_required": True,
        "release_only_after_cap_reached_or_normal_invalidation": True,
    }
    analysis.execution_policy = policy
    audit(
        now,
        "thesis.owner_objective_cap.applied",
        f"reaction_key={key} direction={direction} cap={proposed:.5f} "
        f"opposing_zone={opposing_zone_id} frozen_deepest={deepest:.5f}",
    )
    analysis.trader_brief += (
        f" Owner objective safety cap={proposed:.2f} in front of active opposing "
        f"{str(cap_meta.get('zone_side') or '')} zone {opposing_zone_id}; frozen target "
        f"{deepest:.2f} remains audit truth. Flat-owner cap validity is measured from the "
        f"current executable quote, not the historical ownership anchor {anchor:.2f}. "
        "No live position target was changed."
    )


def reconcile_live_owner_objective_cap(
    analysis: Analysis,
    snapshot: MarketSnapshot,
) -> Analysis:
    """Re-evaluate the flat-owner opposing-zone cap on every live plan poll.

    Full analysis may run while Sequence heartbeat truth is temporarily stale. In
    that case the normal reconciliation correctly defers. This idempotent live
    path retries once fresh Sequence telemetry proves zero open positions, so a
    newly valid opposing HTF zone cannot be ignored until the next analysis cycle.
    It may only tighten lifecycle/runway truth; it never mutates live-position TP.
    """
    if not SETTINGS.paper_only or analysis is None or snapshot is None:
        return analysis

    owner = _active_owner_row(int(snapshot.sent_at))
    if owner is None:
        return analysis

    previous_meta = dict((analysis.execution_policy or {}).get("active_thesis") or {})
    owner_zone = _ownership_zone_snapshot(owner)
    if owner_zone is None:
        owner_zone = next(
            (z for z in list(analysis.zones or []) if _matches_owner(z, owner)),
            None,
        )
    _reconcile_owner_objective_cap(analysis, snapshot, owner, owner_zone)

    # Cap application refreshes active_thesis from persisted owner truth. Preserve
    # independent late-stage-location fields that belong to the current analysis.
    policy = dict(analysis.execution_policy or {})
    meta = dict(policy.get("active_thesis") or {})
    for key in (
        "late_stage_reacquisition_required",
        "late_stage_reacquisition_satisfied",
        "late_stage_reacquisition_zone_id",
        "late_stage_reacquisition_basis",
    ):
        if key in previous_meta:
            meta[key] = previous_meta[key]
    policy["active_thesis"] = meta
    analysis.execution_policy = policy
    return analysis


def apply_thesis_ownership(analysis: Analysis, snapshot: MarketSnapshot) -> Zone | None:
    """Give a previously acquired live thesis precedence over newly ranked opposite zones."""
    if not SETTINGS.paper_only:
        return None

    _release_interzone_prezone_owner(analysis, snapshot)
    owner = _active_owner_row(int(snapshot.sent_at))
    policy = dict(analysis.execution_policy or {})

    if owner is None:
        policy.pop("late_stage_reacquisition", None)
        policy["active_thesis"] = {
            "contract": THESIS_OWNERSHIP_CONTRACT,
            "locked": False,
            "reason": "NO_ACQUIRED_NONTERMINAL_THESIS",
            "interaction_alone_never_locks": True,
        }
        analysis.execution_policy = policy
        return None

    previous_selected = analysis.selected_zone_id
    status = str(owner.get("status") or "INTERACTING")
    direction = str(owner.get("direction") or Direction.NEUTRAL.value)

    # Capture the CURRENT freshly ranked same-direction zone before replacing it
    # with the frozen execution owner for lifecycle/display continuity.
    current_same_direction_zone = next(
        (z for z in analysis.zones if z.original_direction.value == direction),
        None,
    )
    late_stage_reacquisition = _late_stage_reacquisition_state(
        owner,
        current_same_direction_zone,
        snapshot,
    )
    policy["late_stage_reacquisition"] = late_stage_reacquisition
    analysis.execution_policy = policy

    frozen = _ownership_zone_snapshot(owner)
    frozen = _enrich_legacy_owner_snapshot(analysis, owner, frozen)
    owner_zone = frozen if frozen is not None else next((z for z in analysis.zones if _matches_owner(z, owner)), None)

    if owner_zone is not None and frozen is not None:
        # Replace the newly ranked same-direction display zone with the exact zone
        # that acquired execution. This keeps the public map at one zone per side
        # while preventing geometry/id drift from stealing or blocking authority.
        replaced = False
        rebuilt: list[Zone] = []
        for current in analysis.zones:
            if current.original_direction.value == direction and not replaced:
                rebuilt.append(owner_zone)
                replaced = True
            elif current.original_direction.value != direction:
                rebuilt.append(current)
        if not replaced:
            rebuilt.insert(0, owner_zone)
        analysis.zones = rebuilt[:2]

    policy["active_thesis"] = _owner_meta(owner, owner_zone)
    analysis.execution_policy = policy
    _reconcile_owner_objective_cap(analysis, snapshot, owner, owner_zone)

    # Objective-cap reconciliation may refresh active_thesis. Reattach the
    # independent late-stage location gate afterward so downstream plan safety
    # cannot mistake historical ownership for fresh entry location.
    policy = dict(analysis.execution_policy or {})
    active_meta = dict(policy.get("active_thesis") or {})
    active_meta.update(
        {
            "late_stage_reacquisition_required": bool(late_stage_reacquisition.get("required")),
            "late_stage_reacquisition_satisfied": bool(late_stage_reacquisition.get("satisfied")),
            "late_stage_reacquisition_zone_id": str(late_stage_reacquisition.get("current_zone_id") or ""),
            "late_stage_reacquisition_basis": str(late_stage_reacquisition.get("basis") or ""),
        }
    )
    policy["active_thesis"] = active_meta
    policy["late_stage_reacquisition"] = late_stage_reacquisition
    analysis.execution_policy = policy

    if owner_zone is not None:
        _sync_owner_public_map(analysis, owner_zone)

    if owner_zone is None:
        analysis.selected_zone_id = ""
        analysis.approved = False
        if "ACTIVE_THESIS_OWNER_SNAPSHOT_UNAVAILABLE" not in analysis.guards:
            analysis.guards.append("ACTIVE_THESIS_OWNER_SNAPSHOT_UNAVAILABLE")
        if "ACTIVE_THESIS_OWNER_NOT_IN_CURRENT_MAP" not in analysis.guards:
            analysis.guards.append("ACTIVE_THESIS_OWNER_NOT_IN_CURRENT_MAP")
        analysis.trader_brief += (
            f" Active acquired thesis lock={direction} ({status}, {owner.get('ownership_authority','')}). "
            "Its frozen ownership-zone snapshot is unavailable, so execution fails closed until lifecycle release."
        )
        return None

    analysis.selected_zone_id = owner_zone.zone_id
    owner_zone.notes = [
        f"thesis_owner:{direction}:{status}",
        *[n for n in owner_zone.notes if not str(n).startswith("thesis_owner:")],
    ]

    if bool(late_stage_reacquisition.get("required")):
        if bool(late_stage_reacquisition.get("satisfied")):
            analysis.trader_brief += (
                f" Late-stage owner location reacquired through current {direction} zone "
                f"{late_stage_reacquisition.get('current_zone_id','')} "
                f"({late_stage_reacquisition.get('basis','')}); fresh M1 confirmation is still mandatory."
            )
        else:
            analysis.trader_brief += (
                f" Late-stage owner preserved, but fresh execution is suspended after "
                f"{late_stage_reacquisition.get('completed_targets',0)} completed objectives until the CURRENT "
                f"{direction} HTF zone is reacquired. Historical ownership alone cannot authorize another entry."
            )

    if previous_selected and previous_selected != owner_zone.zone_id:
        analysis.trader_brief += (
            f" Active acquired thesis lock={direction} ({status}) on {owner_zone.zone_id}; "
            f"newly ranked {previous_selected} remains map/context only and has no M1 authority until "
            "the acquired thesis is invalidated or completes its deepest effective liquidity objective."
        )
    else:
        analysis.trader_brief += (
            f" Active acquired thesis lock={direction} ({status}) on {owner_zone.zone_id}; same-direction M1 "
            "confirmation remains mandatory and opposite-side execution is blocked."
        )
    return owner_zone
