import hashlib
import json
from pathlib import Path

from app.config import SETTINGS


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "mt5" / "stable" / "manifest.json"


def test_professional_release_contract_is_self_consistent():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # Cloud version advances independently from the MT5 stable package. Validate
    # that code exposes a semantic cloud release, but do not pin it to an obsolete
    # cloud build number when the MT5 package itself has not changed.
    cloud_parts = SETTINGS.app_version.split(".")
    assert len(cloud_parts) == 3 and all(part.isdigit() for part in cloud_parts)
    assert tuple(map(int, cloud_parts)) >= (6, 5, 88)
    assert manifest["release"] == "6.3.46"
    assert manifest["data_bridge_version"] == "1.58"
    assert manifest["sequence_ea_version"] == "3.53"

    bridge = next(item for item in manifest["files"] if item["role"] == "data_bridge")
    assert bridge["name"] == "InstitutionalSMC_DataBridge_v1_58_EntryRunwayTruth.mq5"
    bridge_source = ROOT / bridge["path"]
    assert bridge_source.exists()
    bridge_digest = hashlib.sha256(bridge_source.read_bytes()).hexdigest()
    assert bridge_digest == bridge["sha256"]

    renderer = next(item for item in manifest["support_files"] if item["role"] == "zone_renderer")
    renderer_source = ROOT / renderer["path"]
    assert renderer_source.exists()
    renderer_digest = hashlib.sha256(renderer_source.read_bytes()).hexdigest()
    assert renderer_digest == renderer["sha256"]
    renderer_text = renderer_source.read_text(encoding="utf-8")
    assert "THESIS OWNER" in renderer_text
    assert "M1 HANDOFF | SEQUENCE GATE REQUIRED" in renderer_text
    assert "MAP VALID / RETEST PENDING" in renderer_text
    assert "TZR_DisplayState" in renderer_text

    bridge_core = next(item for item in manifest["support_files"] if item["role"] == "data_bridge_core")
    bridge_core_source = ROOT / bridge_core["path"]
    assert bridge_core_source.exists()
    bridge_core_digest = hashlib.sha256(bridge_core_source.read_bytes()).hexdigest()
    assert bridge_core_digest == bridge_core["sha256"]

    parity = next(item for item in manifest["support_files"] if item["role"] == "sniper_contract_parity")
    parity_source = ROOT / parity["path"]
    assert parity_source.exists()
    parity_digest = hashlib.sha256(parity_source.read_bytes()).hexdigest()
    assert parity_digest == parity["sha256"]
    assert parity["target"] == "Include\\TradeZoneCore"

    seq = next(item for item in manifest["files"] if item["role"] == "sequence_ea")
    assert seq["name"] == "InstitutionalSMC_SequenceEA_v3_53_PDAlternatives_Demo.mq5"
    source = ROOT / seq["path"]
    assert source.exists()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == seq["sha256"]

    required = {
        "outer_zone_liquidity_sweep_execution_authority",
        "core_not_required_after_proven_zone_sweep",
        "frozen_execution_owner_zone_id",
        "exact_frozen_owner_payload_mirror",
        "release_safe_owner_mirror_tombstone",
        "cloud_terminal_owner_resurrection_block",
        "zone_sweep_reaction_confirmed_without_core",
        "zone_sweep_objective_progress_from_handoff_anchor",
        "paper_ai_no_provider_fallback",
        "execution_pipeline_integration_gate",
        "safety_block_preserves_owner_mirror_and_plan_parity",
        "safety_block_suspends_orders_not_plan_sync",
        "cloud_live_block_keeps_execution_authority_visible",
        "active_owner_supersedes_dormant_accepted_flip",
        "next_open_owner_objective_runway_guard",
        "finalized_mt5_plan_dashboard_truth",
        "active_owner_priority_before_flip_authority_mutation",
        "secondary_zone_thin_edge_overlap",
        "nearest_qualified_secondary_battlefield",
        "spread_guard_suspends_orders_not_thesis",
        "safety_hold_dashboard_semantics",
        "owner_mirror_updates_before_live_block",
        "runtime_journal_component_truth",
        "current_sequence_entry_tag_classification",
        "persistent_initial_risk_basis_after_be",
        "m5_runner_trail_after_break_even",
        "runner_risk_history_recovery",
        "compile_safe_databridge_preprocessor_contract",
        "idempotent_journal_event_keys",
        "mt5_journal_history_backfill",
        "position_stable_journal_aggregation",
        "journal_recovery_after_cloud_redeploy",
        "objective_progress_truth_dashboard",
        "execution_truth_chart_status",
        "legacy_no_trade_overlay_cleanup",
        "journal_execution_group_aggregation",
        "journal_version_provenance_separation",
        "journal_position_metadata_persistence",
        "journal_history_metadata_provenance",
        "mql5_tester_guard_compile_fix",
        "installer_compile_diagnostics",
        "reentry_value_requires_closed_m1_reaction",
        "reentry_pd_array_accepted_invalidation_guard",
        "reentry_signal_freshness_guard",
        "reentry_limit_terminal_gate",
        "entry_decision_audit_telemetry",
        "sequence_335_truth_overlay",
        "reentry_confirmation_overlay",
        "thesis_entry_limit_overlay",
        "post_handoff_closed_m1_value_reaction",
        "post_handoff_signal_freshness_guard",
        "post_handoff_pd_array_invalidation_guard",
        "post_handoff_target_already_traded_guard",
        "minimum_rr_enforced_at_order_gate",
        "entry_decision_rr_audit",
        "sequence_336_truth_overlay",
        "liquidity_handoff_live_target_preownership_guard",
        "ownership_brief_lifecycle_truth",
        "journal_immediate_resync_on_cloud_version_change",
        "journal_periodic_continuity_resync",
        "context_grade_risk_matrix",
        "touch_mitigation_telemetry_only",
        "fixed_10000_research_risk_anchor",
        "trend_countertrend_risk_scaling",
        "non_compounding_validation_capital_anchor",
        "ordercalcprofit_risk_sizing",
        "subminimum_lot_fail_closed",
        "aggregate_split_volume_cap",
        "sequence_338_truth_overlay",
        "databridge_147_sequence_338_truth",
        "universal_closed_m1_value_reaction_confirmation",
        "primary_sniper_closed_m1_confirmation",
        "continuation_rescue_closed_m1_confirmation",
        "escape_pullback_closed_m1_confirmation",
        "accepted_flip_closed_m1_confirmation",
        "post_formation_reaction_only",
        "professional_confirmation_floor",
        "sequence_339_truth_overlay",
        "databridge_148_sequence_339_truth",
        "publication_time_zone_rendering",
        "no_retrospective_prepublication_zone_shading",
        "accepted_zone_breaker_pd_array",
        "accepted_zone_breaker_retest_mss_displacement_entry",
        "accepted_zone_breaker_no_chase",
        "master_sniper_contract_parity_v1",
        "cloud_mt5_contract_fingerprint",
        "qualified_mitigation_truth",
        "fail_closed_sniper_contract_gate",
        "sequence_342_parity_runtime",
        "databridge_151_sequence_342_truth",
        "verified_master_sniper_history_window_sync",
        "calendar_span_history_guard",
        "dxy_extended_depth_confluence_only",
        "map_validity_execution_readiness_separation",
        "invalidated_zone_flip_context_chart_comment",
        "canonical_primary_map_count",
        "mt5_watch_only_reason_parity",
        "human_readable_zone_lifecycle_labels",
        "first_entry_zone_distal_stop_floor",
        "zone_stop_spread_atr_broker_buffer",
        "zone_stop_min_rr_fail_closed",
        "strategic_multimodel_execution",
        "momentum_pullback_execution",
        "vwap_proxy_reclaim_execution",
        "opening_range_retest_execution",
        "cloud_local_regime_dual_gate",
        "strategic_model_reduced_risk",
        "strategic_model_fresh_pd_array",
        "strategic_model_closed_m1_confirmation",
        "strategic_model_zone_distal_stop",
        "entry_specific_m1_runway_candidate_window",
        "actual_entry_runway_order_gate",
        "rolling_upgrade_runway_compatibility_guard",
        "runway_gate_dashboard_truth",
    }
    assert required.issubset(set(manifest["channel_features"]))
