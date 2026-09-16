from __future__ import annotations

from datetime import datetime, timezone

from .ai import validate_with_ai
from .config import SETTINGS
from .db import audit, latest_analysis, latest_snapshot, save_analysis
from .dynamic_continuation_zoning import apply_dynamic_continuation_rezone
from .execution_models import build_execution_overlay, regime_brief
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
        "A_OR_A_PLUS_EXECUTION_TIER",
        "CORRECT_SIDE_OF_CURRENT_PRICE",
        "INTRADAY_REACHABILITY",
        "FRESHNESS",
        "GRADE",
        "HTF_AUTHORITY",
        "CONFLUENCE_QUALITY",
    ]
    zone_map["nearer_valid_a_zone_can_outrank_remote_fresher_a_zone"] = True
    policy["public_zone_map"] = zone_map
    a.execution_policy = policy


def _stamp_execution_authority(a: Analysis, ready_zone, liquidity_handoff: dict) -> str:
    authority = "NONE"
    zone_id = ""
    risk_multiplier = 1.0
    if ready_zone is not None and a.selected_zone_id == ready_zone.zone_id:
        authority = "HTF_CORE_HANDOFF"
        zone_id = ready_zone.zone_id
    elif bool(liquidity_handoff.get("active")):
        authority = "LIQUIDITY_REVERSAL_HANDOFF"
        zone_id = str(liquidity_handoff.get("context_zone_id") or "")
        risk_multiplier = float(liquidity_handoff.get("risk_multiplier") or 0.50)

    policy = dict(a.execution_policy or {})
    policy["execution_authority"] = {
        "authority": authority,
        "zone_id": zone_id,
        "risk_multiplier": risk_multiplier,
        "paper_only": True,
        "full_m1_sequence_required": authority != "NONE",
        "ownership_acquired": False,
    }
    a.execution_policy = policy
    return authority


def _acquire_final_ownership(a: Analysis, s, authority: str, liquidity_handoff: dict) -> tuple[str, dict | None]:
    """Persist thesis lock only after the handoff survives all current cloud gates."""
    if authority == "NONE" or not bool(a.approved):
        return authority, None

    policy = dict(a.execution_policy or {})
    auth_meta = dict(policy.get("execution_authority") or {})
    zone_id = str(auth_meta.get("zone_id") or a.selected_zone_id or "")
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


async def run_analysis(reason: str = "MANUAL") -> Analysis:
    s = latest_snapshot()
    if s is None:
        raise RuntimeError("No market snapshot available")
    now = int(datetime.now(timezone.utc).timestamp())

    # Single authoritative base zoning path: the prompt-driven institutional engine.
    a = build_prompt_analysis(s, now)
    # PAPER/DEMO ONLY: after a confirmed directional expansion, allow a fresh
    # displacement/FVG retest with nearby structural liquidity to replace a remote
    # same-direction primary. Exhausted B+/multi-touch countertrend zones are kept
    # as lifecycle/context truth but removed from the execution map. An already-
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

    # Authority 1: normal HTF tactical-core handoff.
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
                a.trader_brief += " AI validation: primary prompt zone ARMED; execution waits for HTF core or confirmed liquidity-reversal handoff."
        else:
            a.trader_brief += " AI validation: no executable prompt zone is selected; weaker/context zones may remain visible."
        if risks:
            a.guards.extend([f"AI:{x}" for x in risks])

        if selected and not execution_selected:
            a.approved = False
        elif SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and execution_selected and not ok:
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
            # PAPER research must not become structurally deadlocked by an external
            # AI-provider outage. Deterministic handoff + MT5 M1 sequence remain the
            # authority; all spread/news/snapshot/risk/target guards remain intact.
            a.approved = True
            policy = dict(a.execution_policy or {})
            policy["paper_ai_fallback"] = {
                "active": True,
                "reason": "AI_PROVIDER_UNAVAILABLE",
                "authority": authority,
                "real_money_allowed": False,
            }
            a.execution_policy = policy
            a.guards.append("AI_PROVIDER_UNAVAILABLE_ADVISORY_PAPER_ONLY")
            a.trader_brief += " AI provider unavailable; PAPER deterministic execution authority remains active for research only."
        elif a.selected_zone_id:
            a.approved = False
            a.guards.append("AI_PROVIDER_UNAVAILABLE")
        else:
            a.trader_brief += " AI validation unavailable; prompt zones remain analysis-only locations."

    # Final ownership acquisition occurs only after deterministic handoff plus the
    # current cloud approval path (or the explicit PAPER-only AI outage fallback).
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
