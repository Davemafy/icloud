import hashlib
import json
from pathlib import Path

from app.config import SETTINGS


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "mt5" / "stable" / "manifest.json"


def test_professional_release_contract_is_self_consistent():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert SETTINGS.app_version == "6.5.61"
    assert manifest["release"] == "6.3.28"
    assert manifest["data_bridge_version"] == "1.47"
    assert manifest["sequence_ea_version"] == "3.38"

    bridge = next(item for item in manifest["files"] if item["role"] == "data_bridge")
    assert bridge["name"] == "InstitutionalSMC_DataBridge_v1_47_ContextGradeRiskTruth.mq5"
    bridge_source = ROOT / bridge["path"]
    assert bridge_source.exists()
    bridge_digest = hashlib.sha256(bridge_source.read_bytes()).hexdigest()
    assert bridge_digest == bridge["sha256"] == "378dd6536c0470659ba17884754756da1d4a8a8fe21cdd63676bab803ebc6b12"

    bridge_core = next(item for item in manifest["support_files"] if item["role"] == "data_bridge_core")
    bridge_core_source = ROOT / bridge_core["path"]
    assert bridge_core_source.exists()
    bridge_core_digest = hashlib.sha256(bridge_core_source.read_bytes()).hexdigest()
    assert bridge_core_digest == bridge_core["sha256"] == "990cc537380baa9df89551a882a31a124a3177693d694be367ff521526a8d8e9"

    seq = next(item for item in manifest["files"] if item["role"] == "sequence_ea")
    assert seq["name"] == "InstitutionalSMC_SequenceEA_v3_38_ContextGradeRiskAutoSize_Demo.mq5"
    source = ROOT / seq["path"]
    assert source.exists()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == seq["sha256"] == "13e47adad74199b27272f44654f1f1113ddb9a580d6549cb3a06639c81174701"

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
        "safety_block_preserves_owner_mirror",
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
        "bplus_watch_only_no_new_entry_budget",
        "a_second_touch_reduced_risk_eligibility",
        "fixed_10000_research_risk_anchor",
        "trend_countertrend_risk_scaling",
        "non_compounding_validation_capital_anchor",
        "ordercalcprofit_risk_sizing",
        "subminimum_lot_fail_closed",
        "aggregate_split_volume_cap",
        "sequence_338_truth_overlay",
        "databridge_147_sequence_338_truth",
    }
    assert required.issubset(set(manifest["channel_features"]))
