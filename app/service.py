from __future__ import annotations

from datetime import datetime, timezone

from .ai import validate_with_ai
from .config import SETTINGS
from .db import audit, latest_analysis, latest_snapshot, save_analysis
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
from .risk_matrix import matrix_payload
from .prompt_contract import apply_prompt_confirmation_contract
from .prompt_intraday_selection import PROMPT_SELECTION_CONTRACT, install_prompt_intraday_selection
from .secondary_zone_policy import apply_secondary_zone_policy
from .target_revalidation import activation_target_truth, apply_target_revalidation
from .thesis_hard_release import hard_release_stale_thesis
from .thesis_ownership_policy import (
    acquire_execution_ownership,
    apply_thesis_ownership,
    install_thesis_ai_contract,
)
from .watch_ready import promote_watch_to_m1_ready
from .zone_reaction_lifecycle import (
    apply_publication_truth,
    attach_lifecycle,
    register_analysis_zones,
    update_zone_publication_contacts,
    update_zone_reactions,
)
from .zone_runtime_policy import (
    install_prompt_market_side_policy,
    install_zone_geometry_policy,
)

# MASTER SNIPER is installed before any analysis is built. It is the single
# authority for BUY and SELL zone formation, geometry and structural validity.
# Downstream modules may rank/validate/execute/manage zones, but may not replace
# them with synthetic FVG/liquidity-centered geometry.
install_zone_geometry_policy()
install_prompt_market_side_policy()
install_prompt_intraday_selection()
install_thesis_ai_contract()
install_liquidity_reversal_ai_contract()


def _stamp_prompt_selection_contract(a: Analysis) -> None:
    policy = dict(a.execution_policy or {})
    zone_map = dict(policy.get("public_zone_map") or {})
    zone_map["prompt_contract_ref"] = PROMPT_SELECTION_CONTRACT
    zone_map["zone_formation_authority"] = "MASTER_SNIPER_PROMPT_ONLY"
    zone_map["downstream_rezoning_allowed"] = False
    zone_map["selection_priority"] = [
        "STRUCTURAL_VALIDITY",
        "GRADE_SCALED_EXECUTION_TIER",
        "INTRADAY_REACHABILITY",
        "FRESHNESS",
        "GRADE",
        "HTF_AUTHORITY",
        "CONFLUENCE_QUALITY",
    ]
    zone_map["nearer_valid_zone_can_outrank_remote_fresher_zone"] = True
    zone_map["context_grade_risk_matrix"] = matrix_payload()
    zone_map["four_zone_map_contract"] = {
        "primary_per_side": 1,
        "reserve_per_side": 1,
        "max_visible_zones": 4,
        "same_side_simultaneous_ownership": False,
        "reserve_promotes_only_after_primary_invalidation_and_fresh_requalification": True,
    }
    policy["public_zone_map"] = zone_map
    a.execution_policy = policy


def _stamp_execution_authority(a: Analysis, ready_zone, liquidity_handoff: dict) -> str:
    """Resolve current execution authority without discarding a live owner handoff."""
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
        and owner_authority in {"HTF_CORE_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF", "LIQUIDITY_REVERSAL_HANDOFF"}
        and owner_zone_id
        and owner_zone_id == str(a.selected_zone_id or "")
    )
    if owner_live:
        authority = owner_authority
        zone_id = owner_zone_id
        risk_multiplier = 0.50 if authority == "LIQUIDITY_REVERSAL_HANDOFF" else 0.65 if authority == "HTF_ZONE_SWEEP_HANDOFF" else 1.0
    elif ready_zone is not None and a.selected_zone_id == ready_zone.zone_id:
        window = dict(policy.get("execution_window") or {})
        location_mode = str(window.get("mode") or "")
        sweep_note = any(str(note).startswith("execution_location:LATCHED_AFTER_ZONE_SWEEP") or "ZONE_SWEEP_HANDOFF" in str(note) for note in ready_zone.notes)
        authority = "HTF_ZONE_SWEEP_HANDOFF" if location_mode == "LATCHED_AFTER_ZONE_SWEEP" or sweep_note else "HTF_CORE_HANDOFF"
        zone_id = ready_zone.zone_id
        risk_multiplier = 0.65 if authority == "HTF_ZONE_SWEEP_HANDOFF" else 1.0
    elif bool(liquidity_handoff.get("active")):
        authority = "LIQUIDITY_REVERSAL_HANDOFF"
        zone_id = str(liquidity_handoff.get("context_zone_id") or "")
        risk_multiplier = float(liquidity_handoff.get("risk_multiplier") or 0.50)
    policy["execution_authority"] = {
        "authority": authority, "zone_id": zone_id, "risk_multiplier": risk_multiplier,
        "paper_only": True, "full_m1_sequence_required": authority != "NONE",
        "ownership_acquired": owner_live, "owner_continuation": owner_live,
        "ownership_acquired_at": int(thesis.get("ownership_acquired_at") or 0) if owner_live else 0,
    }
    a.execution_policy = policy
    return authority


def _acquire_final_ownership(a: Analysis, s, authority: str, liquidity_handoff: dict) -> tuple[str, dict | None]:
    if authority == "NONE":
        return authority, None
    policy = dict(a.execution_policy or {})
    auth_meta = dict(policy.get("execution_authority") or {})
    zone_id = str(auth_meta.get("zone_id") or a.selected_zone_id or "")
    thesis = dict(policy.get("active_thesis") or {})
    if bool(thesis.get("locked") and str(thesis.get("owner_zone_id") or "") == zone_id and str(thesis.get("ownership_authority") or "") == authority and thesis.get("objective_open", True)):
        auth_meta["ownership_acquired"] = True
        auth_meta["owner_continuation"] = True
        auth_meta["ownership_acquired_at"] = int(thesis.get("ownership_acquired_at") or 0)
        policy["execution_authority"] = auth_meta
        a.execution_policy = policy
        return authority, thesis
    target_zone = next((z for z in a.zones if z.zone_id == zone_id), None)
    if target_zone is None:
        auth_meta.update({"authority": "NONE", "attempted_authority": authority, "ownership_acquired": False, "block_reason": "TARGET_ZONE_NOT_FOUND"})
        policy["execution_authority"] = auth_meta
        a.execution_policy = policy
        return "NONE", None
    activation_reference = float(s.ask if target_zone.original_direction.value == "BUY" else s.bid)
    target_truth = activation_target_truth(target_zone, s, activation_reference, activation_ts=int(s.sent_at), reference_basis="LIVE_EXECUTION_HANDOFF_REFERENCE")
    target_policy = dict(policy.get("target_revalidation") or {})
    per_zone = dict(target_policy.get("per_zone") or {})
    per_zone[target_zone.zone_id] = target_truth
    target_policy["per_zone"] = per_zone
    policy["target_revalidation"] = target_policy
    if not bool(target_truth.get("authority_safe")):
        block_reason = "NO_LIVE_DIRECTIONAL_TARGET" if authority == "LIQUIDITY_REVERSAL_HANDOFF" else "TARGET_REMAP_REQUIRED_AT_ACTIVATION"
        auth_meta.update({"authority": "NONE", "attempted_authority": authority, "ownership_acquired": False, "owner_continuation": False, "block_reason": block_reason})
        policy["execution_authority"] = auth_meta
        a.execution_policy = policy
        return "NONE", None
    if authority == "LIQUIDITY_REVERSAL_HANDOFF" and not has_live_directional_target(target_zone, s):
        return "NONE", None
    if not bool(a.approved):
        return authority, None
    anchor = float(liquidity_handoff.get("liquidity_price") or s.mid) if authority == "LIQUIDITY_REVERSAL_HANDOFF" else float(s.mid)
    owner = acquire_execution_ownership(a, s, authority, zone_id, anchor)
    if owner is None:
        return "NONE", None
    return authority, owner


def _activate_paper_ai_fallback(a: Analysis, authority: str, reason: str) -> bool:
    if not SETTINGS.paper_only or authority == "NONE" or not a.selected_zone_id:
        return False
    a.approved = True
    a.ai_approved = False
    policy = dict(a.execution_policy or {})
    policy["paper_ai_fallback"] = {"active": True, "reason": str(reason or "AI_PROVIDER_UNAVAILABLE"), "authority": authority, "real_money_allowed": False}
    a.execution_policy = policy
    if "AI_PROVIDER_UNAVAILABLE_ADVISORY_PAPER_ONLY" not in a.guards:
        a.guards.append("AI_PROVIDER_UNAVAILABLE_ADVISORY_PAPER_ONLY")
    return True


async def run_analysis(reason: str = "MANUAL") -> Analysis:
    s = latest_snapshot()
    if s is None:
        raise RuntimeError("No market snapshot available")
    now = int(datetime.now(timezone.utc).timestamp())

    # SINGLE ZONE FACTORY: Master Sniper prompt engine. This applies equally to
    # BUY/SELL and trend/countertrend. Nothing downstream may re-zone it.
    a = build_prompt_analysis(s, now)
    if SETTINGS.paper_only:
        register_analysis_zones(a)

    apply_prompt_confirmation_contract(a, s)
    _stamp_prompt_selection_contract(a)
    apply_secondary_zone_policy(a, s)
    attach_lifecycle(a)
    update_zone_publication_contacts(a, s)
    update_zone_reactions(a, s)
    apply_publication_truth(a, s)
    hard_release_stale_thesis(a, s)
    apply_thesis_ownership(a, s)
    apply_target_revalidation(a, s)
    apply_liquidity_objective_policy(a, s)
    liquidity_handoff = apply_liquidity_reversal_handoff(a, s)
    ready_zone = promote_watch_to_m1_ready(a, s)
    authority = _stamp_execution_authority(a, ready_zone, liquidity_handoff)
    authority, _ = _acquire_final_ownership(a, s, authority, liquidity_handoff)
    build_execution_overlay(a, s)
    regime_brief(a, s)
    try:
        ai_result = await validate_with_ai(a, s)
        if ai_result is not None:
            a.ai_approved = bool(ai_result.approved)
    except Exception as exc:
        _activate_paper_ai_fallback(a, authority, str(exc))
    capture_cloud_candidates(a, s)
    save_analysis(a)
    audit("analysis", {"reason": reason, "selected_zone_id": a.selected_zone_id, "zone_formation_authority": "MASTER_SNIPER_PROMPT_ONLY"})
    return a
