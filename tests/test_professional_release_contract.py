import hashlib
import json
from pathlib import Path

from app.config import SETTINGS


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "mt5" / "stable" / "manifest.json"


def test_professional_release_contract_is_self_consistent():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert SETTINGS.app_version == "6.5.41"
    assert manifest["release"] == "6.3.21"
    assert manifest["data_bridge_version"] == "1.41"
    assert manifest["sequence_ea_version"] == "3.34"

    bridge = next(item for item in manifest["files"] if item["role"] == "data_bridge")
    assert bridge["name"] == "InstitutionalSMC_DataBridge_v1_41_JournalProvenance.mq5"
    bridge_source = ROOT / bridge["path"]
    assert bridge_source.exists()
    bridge_digest = hashlib.sha256(bridge_source.read_bytes()).hexdigest()
    assert bridge_digest == bridge["sha256"] == "58783b7a4aed02eb69cc262faec130f9503e4553360b5524a31865a74edc077b"

    bridge_core = next(item for item in manifest["support_files"] if item["role"] == "data_bridge_core")
    bridge_core_source = ROOT / bridge_core["path"]
    assert bridge_core_source.exists()
    bridge_core_digest = hashlib.sha256(bridge_core_source.read_bytes()).hexdigest()
    assert bridge_core_digest == bridge_core["sha256"] == "6f4649717a488c708e9fcfd1d7d6b710d23d060b646612d031638b53fd163910"

    seq = next(item for item in manifest["files"] if item["role"] == "sequence_ea")
    assert seq["name"] == "InstitutionalSMC_SequenceEA_v3_34_PersistentRunnerRisk_Demo.mq5"
    source = ROOT / seq["path"]
    assert source.exists()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == seq["sha256"] == "79378339b39ab6af268eb4e71f42d4ca1a2b33d988b5a488b8a7afa956c6565d"

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
    }
    assert required.issubset(set(manifest["channel_features"]))
