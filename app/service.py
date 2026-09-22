from __future__ import annotations

from datetime import datetime, timezone

from .ai import validate_with_ai
from .config import SETTINGS
from .db import audit, latest_analysis, latest_snapshot, save_analysis
from .dynamic_continuation_zoning import apply_dynamic_continuation_rezone
from .execution_models import build_execution_overlay, regime_brief
from .execution_safety import has_live_directional_target
from .institutional_two_zone import build_prompt_analysis
from .liquidity_objective_policy import apply_liquidity_objective_policy
from .liquidity_reversal_handoff import (
    apply_liquidity_reversal_handoff,
    install_liquidity_reversal_ai_contract,
)
from .ml_foundation import capture_cloud_candidates
from .models import Analysis
from .prompt_contract import apply_prompt_confirmation_contract
from .prompt_intraday_selection import PROMPT_SELECTION_CONTRACT, install_prompt_intraday_selection
from .secondary_zone_policy import apply_secondary_zone_policy
from .thesis_hard_release import hard_release_stale_thesis
from .thesis_ownership_policy import (
    acquire_execution_ownership,
    apply_thesis_ownership,
    install_thesis_ai_contract,
)
from .watch_ready import promote_watch_to_m1_ready
from .zone_reaction_lifecycle import (
    attach_lifecycle,
    register_analysis_zones,
    update_zone_reactions,
)
from .zone_runtime_policy import (
    install_prompt_market_side_policy,
    install_zone_geometry_policy,
)

# PAPER/DEMO ONLY: install the master-sniper prompt zoning contract before any
# analysis is built. Geometry and market-side validity are qualification rules;
# intraday selection ranks already-valid zones by today's relevance.
install_zone_geometry_policy()
install_prompt_market_side_policy()
install_prompt_intraday_selection()
install_thesis_ai_contract()
install_liquidity_reversal_ai_contract()


def _stamp_prompt_selection_contract(a: Analysis) -> None:
    policy = dict(a.execution_policy or {})
    zone_map = dict(policy.get("public_zone_map") or {})
    zone_map["prompt_contract_ref"] = PROMPT_SELECTION_CONTRACT
    zone_map["selection_priority"] = [
        "STRUCTURAL_VALIDITY",
        "GRADE_SCALED_EXECUTION_TIER",
        "CORRECT_SIDE_OF_CURRENT_PRICE",
        "INTRADAY_REACHABILITY",
        "FRESHNESS",
        "GRADE",
        "HTF_AUTHORITY",
        "CONFLUENCE_QUALITY",
    ]
    zone_map["nearer_valid_a_zone_can_outrank_remote_fresher_a_zone"] = True
    zone_map["bplus_is_reduced_risk_not_watch_only"] = True
    zone_map["grade_risk_pct"] = {"A+": 1.00, "A": 0.75, "B+": 0.25}
    policy["public_zone_map"] = zone_map
    a.execution_policy = policy


def _stamp_execution_authority(a: Analysis, ready_zone, liquidity_handoff: dict) -> str:
    """Resolve current execution authority without discarding a live owner handoff.

    Once a thesis has acquired deterministic authority, later re-analysis must not
    downgrade it to WATCH_ONLY merely because price has left the original HTF
    location. The owner remains sticky until lifecycle release; Sequence still
    requires a fresh same-direction M1 structure/displacement/value pattern and
    therefore cannot chase price.
    """
    authority = "NONE"
    zone_id = ""
    risk_multiplier = 1.0
    policy = dict(a.execution_policy or {})
    thesis = dict(policy.get("active_thesis") or {})
    owner_authority = str(thesis.get("ownership_authority") or "")
    owner_zone_id = str(thesis.get("owner_zone_id") or "")
    owner_live = bool(
        thesis.get("locked")
        and thesis.get("objective_open", True)
        and thesis.get("continuation_authority")
        and owner_authority in {
            "HTF_CORE_HANDOFF",
            "HTF_ZONE_SWEEP_HANDOFF",
            "LIQUIDITY_REVERSAL_HANDOFF",
        }
        and owner_zone_id
        and owner_zone_id == str(a.selected_zone_id or "")
    )

    if owner_live:
        authority = owner_authority
        zone_id = owner_zone_id
        risk_multiplier = (
            0.50 if authority == "LIQUIDITY_REVERSAL_HANDOFF"
            else 0.65 if authority == "HTF_ZONE_SWEEP_HANDOFF"
            else 1.0
        )
    elif ready_zone is not None and a.selected_zone_id == ready_zone.zone_id:
        window = dict(policy.get("execution_window") or {})
        location_mode = str(window.get("mode") or "")
        sweep_note = any(
            str(note).startswith("execution_location:LATCHED_AFTER_ZONE_SWEEP")
            or "ZONE_SWEEP_HANDOFF" in str(note)
            for note in ready_zone.notes
        )
        authority = (
            "HTF_ZONE_SWEEP_HANDOFF"
            if location_mode == "LATCHED_AFTER_ZONE_SWEEP" or sweep_note
            else "HTF_CORE_HANDOFF"
        )
        zone_id = ready_zone.zone_id
        risk_multiplier = 0.65 if authority == "HTF_ZONE_SWEEP_HANDOFF" else 1.0
    elif bool(liquidity_handoff.get("active")):
        authority = "LIQUIDITY_REVERSAL_HANDOFF"
        zone_id = str(liquidity_handoff.get("context_zone_id") or "")
        risk_multiplier = float(liquidity_handoff.get("risk_multiplier") or 0.50)

    policy["execution_authority"] = {
        "authority": authority,
        "zone_id": zone_id,
        "risk_multiplier": risk_multiplier,
        "paper_only": True,
        "full_m1_sequence_required": authority != "NONE",
        "ownership_acquired": owner_live,
        "owner_continuation": owner_live,
        "ownership_acquired_at": int(thesis.get("ownership_acquired_at") or 0) if owner_live else 0,
    }
    a.execution_policy = policy
    return authority


def _acquire_final_ownership(a: Analysis, s, authority: str, liquidity_handoff: dict) -> tuple[str, dict | None]:
    """Persist thesis lock after structural/approval handoff gates.

    Execution-time safety holds such as spread still block MT5 orders, but they do
    not erase a valid institutional thesis or prevent its ownership from persisting.
    """
    if authority == "NONE":
        return authority, None

    policy = dict(a.execution_policy or {})
    auth_meta = dict(policy.get("execution_authority") or {})
    zone_id = str(auth_meta.get("zone_id") or a.selected_zone_id or "")
    thesis = dict(policy.get("active_thesis") or {})
    if bool(
        thesis.get("locked")
        and str(thesis.get("owner_zone_id") or "") == zone_id
        and str(thesis.get("ownership_authority") or "") == authority
        and thesis.get("objective_open", True)
    ):
        auth_meta["ownership_acquired"] = True
        auth_meta["owner_continuation"] = True
        auth_meta["ownership_acquired_at"] = int(thesis.get("ownership_acquired_at") or 0)
        policy["execution_authority"] = auth_meta
        a.execution_policy = policy
        return authority, thesis

    if authority == "LIQUIDITY_REVERSAL_HANDOFF":
        zone = next(
            (z for z in a.zones if z.zone_id == zone_id),
            None,
        )
        if zone is None or not has_live_directional_target(zone, s):
            attempted = authority
            auth_meta["authority"] = "NONE"
            auth_meta["attempted_authority"] = attempted
            auth_meta["ownership_acquired"] = False
            auth_meta["owner_continuation"] = False
            auth_meta["block_reason"] = "NO_LIVE_DIRECTIONAL_TARGET"
            policy["execution_authority"] = auth_meta

            lrh_meta = dict(policy.get("liquidity_reversal_handoff") or {})
            lrh_meta["active"] = False
            lrh_meta["authority"] = "NONE"
            lrh_meta["reason"] = "NO_LIVE_DIRECTIONAL_TARGET"
            policy["liquidity_reversal_handoff"] = lrh_meta
            policy.pop("paper_ai_fallback", None)
            a.execution_policy = policy
            a.ai_approved = False
            if "LIQUIDITY_HANDOFF_NO_LIVE_DIRECTIONAL_TARGET" not in a.guards:
                a.guards.append("LIQUIDITY_HANDOFF_NO_LIVE_DIRECTIONAL_TARGET")
            a.trader_brief += (
                " Liquidity-reversal handoff expired before ownership because no "
                "same-direction objective remains beyond live price."
            )
            return "NONE", None

    if not bool(a.approved):
        return authority, None

    anchor = (
        float(liquidity_handoff.get("liquidity_price") or s.mid)
        if authority == "LIQUIDITY_REVERSAL_HANDOFF"
        else float(s.mid)
    )
    owner = acquire_execution_ownership(a, s, authority, zone_id, anchor)
    policy = dict(a.execution_policy or {})
    auth_meta = dict(policy.get("execution_authority") or auth_meta)
    if owner is None:
        attempted = authority
        auth_meta["authority"] = "NONE"
        auth_meta["attempted_authority"] = attempted
        auth_meta["ownership_acquired"] = False
        auth_meta["ownership_acquisition_failed"] = True
        policy["execution_authority"] = auth_meta
        a.execution_policy = policy
        a.approved = False
        if "EXECUTION_OWNERSHIP_ACQUIRE_FAILED" not in a.guards:
            a.guards.append("EXECUTION_OWNERSHIP_ACQUIRE_FAILED")
        a.trader_brief += " Execution handoff failed closed because persistent thesis ownership could not be acquired."
        return "NONE", None

    auth_meta["ownership_acquired"] = True
    auth_meta["ownership_reaction_key"] = str(owner.get("reaction_key") or "")
    auth_meta["ownership_acquired_at"] = int(owner.get("ownership_acquired_at") or 0)
    policy["execution_authority"] = auth_meta
    a.execution_policy = policy
    return authority, owner


def _activate_paper_ai_fallback(a: Analysis, authority: str, reason: str) -> bool:
    """Keep deterministic execution research alive only when the AI layer is unavailable.

    This never converts an explicit AI rejection into approval and is disabled outside
    PAPER mode. Deterministic handoff, MT5 M1 structure/value, spread/news/risk and
    target-direction guards remain mandatory.
    """
    if not SETTINGS.paper_only or authority == "NONE" or not a.selected_zone_id:
        return False
    a.approved = True
    a.ai_approved = False
    policy = dict(a.execution_policy or {})
    policy["paper_ai_fallback"] = {
        "active": True,
        "reason": str(reason or "AI_PROVIDER_UNAVAILABLE"),
        "authority": authority,
        "real_money_allowed": False,
    }
    a.execution_policy = policy
    if "AI_PROVIDER_UNAVAILABLE_ADVISORY_PAPER_ONLY" not in a.guards:
        a.guards.append("AI_PROVIDER_UNAVAILABLE_ADVISORY_PAPER_ONLY")
    note = " AI provider unavailable; PAPER deterministic execution authority remains active for research only."
    if note.strip() not in str(a.trader_brief or ""):
        a.trader_brief += note
    return True


async def run_analysis(reason: str = "MANUAL") -> Analysis:
    s = latest_snapshot()
    if s is None:
        raise RuntimeError("No market snapshot available")
    now = int(datetime.now(timezone.utc).timestamp())

    # Single authoritative base zoning path: the prompt-driven institutional engine.
    a = build_prompt_analysis(s, now)
    # Preserve the original qualified map as lifecycle/context truth before any
    # execution-relevance re-ranking. Since v6.5.20, registration/interaction alone
    # cannot acquire thesis ownership, so this cannot create an execution lock.
    if SETTINGS.paper_only:
        register_analysis_zones(a)
    # PAPER/DEMO ONLY: after a confirmed directional expansion, allow a fresh
    # displacement/FVG retest with nearby structural liquidity to replace a remote
    # same-direction primary. Only genuinely exhausted three-plus-touch countertrend
    # zones are removed from the execution map; eligible B+ remains reduced-risk. An already-
    # acquired thesis is protected and disables this re-ranking.
    apply_dynamic_continuation_rezone(a, s)
    # Includes DXY D1/H1 confirmation and the one user-facing pip/display pass.
    apply_prompt_confirmation_contract(a, s)
    _stamp_prompt_selection_contract(a)
    # PAPER/DEMO ONLY: expose one distinct non-executable Level-2 reserve per
    # side. Reserves never enter analysis.zones and cannot receive M1 authority
    # while the corresponding Level-1 primary remains valid.
    apply_secondary_zone_policy(a, s)

    # PAPER/DEMO ONLY: zoning and objective selection are independent. Preserve
    # a valid HTF zone even when an old nearest-price TP map is poor. Targets are
    # rebuilt from structural liquidity and capped in front of an active opposing
    # institutional zone; session context changes patience, never zone validity.
    apply_liquidity_objective_policy(a, s)
    primary_zones = list(a.zones)

    # Lifecycle records all institutional reactions, but an interaction alone no
    # longer creates execution ownership. Existing pre-v6.5.20 rows migrate with
    # ownership_acquired_at=0 and therefore cannot inherit a stale execution lock.
    if SETTINGS.paper_only:
        register_analysis_zones(a)
        update_zone_reactions(s)
        hard_release_stale_thesis(s)

    # Only a thesis that previously acquired an explicit execution handoff may
    # block the opposite side. Ordinary WATCH/INTERACTING lifecycle records do not.
    thesis_owner = apply_thesis_ownership(a, s)

    # Authority 1: qualified HTF location handoff. The strict tactical core remains
    # valid, but a proven structural-liquidity sweep/reclaim inside the outer zone
    # may now grant M1 SEARCH authority before core touch.
    ready_zone = promote_watch_to_m1_ready(a, s)

    # Authority 2: confirmed structural-liquidity reversal before the remote HTF
    # core. This does NOT promote liquidity into a zone and is disabled whenever a
    # previously acquired live thesis still owns execution.
    liquidity_handoff = (
        apply_liquidity_reversal_handoff(a, s)
        if ready_zone is None
        else {"active": False, "authority": "NONE", "reason": "HTF_CORE_HANDOFF_HAS_PRIORITY"}
    )
    authority = _stamp_execution_authority(a, ready_zone, liquidity_handoff)

    overlay = build_execution_overlay(s, a, reason)
    a.execution_policy = {**a.execution_policy, "multi_model": overlay}
    a.trader_brief += " " + regime_brief(overlay)
    try:
        ok, summary, risks, provider = await validate_with_ai(a, s)
        a.ai_provider = provider
        selected = bool(a.selected_zone_id)
        execution_selected = bool(authority != "NONE" and selected)
        a.ai_approved = bool(ok and execution_selected)
        if execution_selected:
            if summary:
                a.trader_brief += " AI execution validation: " + summary
        elif selected:
            if thesis_owner is not None:
                a.trader_brief += " AI validation: acquired institutional thesis retained; execution waits for same-direction handoff confirmation."
            else:
                a.trader_brief += " AI validation: primary prompt zone ARMED; execution waits for tactical core, qualified zone liquidity-sweep handoff, or confirmed liquidity-reversal handoff."
        else:
            a.trader_brief += " AI validation: no executable prompt zone is selected; weaker/context zones may remain visible."
        if risks:
            a.guards.extend([f"AI:{x}" for x in risks])

        paper_ai_fallback = bool(
            execution_selected
            and not ok
            and SETTINGS.paper_only
            and (
                str(provider).upper() == "NONE"
                or "AI_PROVIDER_UNAVAILABLE" in {str(x) for x in risks}
            )
        )
        if paper_ai_fallback:
            _activate_paper_ai_fallback(a, authority, "AI_PROVIDER_UNAVAILABLE")
        elif selected and not execution_selected:
            a.approved = False
        elif SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and execution_selected and not ok:
            # A real provider's explicit rejection remains fail-closed.
            a.approved = False

        audit(
            now,
            "analysis.ai",
            f"reason={reason} provider={provider} approved={a.ai_approved} "
            f"selected={selected} execution_selected={execution_selected} authority={authority} "
            f"thesis_owner={getattr(thesis_owner, 'zone_id', '') or 'NONE'} "
            f"paper_m1_ready={bool(ready_zone)} liquidity_handoff={bool(liquidity_handoff.get('active'))} "
            f"primary_zones={len(primary_zones)} prompt_zone_engine=2026_09_14_v659 risks={risks}",
        )
    except Exception as exc:
        audit(now, "analysis.ai.error", f"reason={reason} error={type(exc).__name__}:{exc}")
        a.ai_provider = "ERROR"
        a.ai_approved = False
        execution_selected = bool(authority != "NONE" and a.selected_zone_id)
        if execution_selected and SETTINGS.paper_only:
            _activate_paper_ai_fallback(a, authority, f"{type(exc).__name__}:{exc}")
        elif a.selected_zone_id:
            a.approved = False
            a.guards.append("AI_PROVIDER_UNAVAILABLE")
        else:
            a.trader_brief += " AI validation unavailable; prompt zones remain analysis-only locations."

    # Final ownership acquisition occurs after deterministic handoff plus structural
    # approval (or the explicit PAPER-only AI outage fallback). Execution-time safety
    # such as spread is enforced in /mt5/plan and must not erase the thesis lock.
    authority, ownership_row = _acquire_final_ownership(a, s, authority, liquidity_handoff)

    # save_analysis re-registers idempotently; the pre-registration above is only
    # to make lifecycle truth available before ownership/M1 selection in this run.
    save_analysis(a)
    attach_lifecycle(a)
    if SETTINGS.ml_data_enabled:
        try:
            capture_cloud_candidates(a, s, reason)
        except Exception as exc:
            audit(now, "ml.cloud.error", f"reason={reason} analysis_id={a.analysis_id} error={type(exc).__name__}:{exc}")

    audit(
        now,
        "analysis.completed",
        f"reason={reason} id={a.analysis_id} approved={a.approved} zones={len(a.zones)} "
        f"selected={a.selected_zone_id or 'NONE'} thesis_owner={getattr(thesis_owner, 'zone_id', '') or 'NONE'} "
        f"authority={authority} ownership_acquired={bool(ownership_row)} "
        f"paper_m1_ready={bool(ready_zone)} liquidity_handoff={bool(liquidity_handoff.get('active'))} "
        f"prompt_zone_engine=2026_09_14_v659 regime={overlay['regime']['name']} ml_data={SETTINGS.ml_data_enabled}",
    )
    return a


def active_analysis() -> Analysis | None:
    a = latest_analysis(ai_required=False)
    return attach_lifecycle(a) if a is not None else None
