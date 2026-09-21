import hashlib
import json
from pathlib import Path

from app.config import SETTINGS


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "mt5" / "stable" / "manifest.json"


def test_professional_release_contract_is_self_consistent():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert SETTINGS.app_version == "6.5.35"
    assert manifest["release"] == "6.3.16"
    assert manifest["data_bridge_version"] == "1.37"
    assert manifest["sequence_ea_version"] == "3.33"

    bridge = next(item for item in manifest["files"] if item["role"] == "data_bridge")
    assert bridge["name"] == "InstitutionalSMC_DataBridge_v1_37_RuntimeJournalTruth.mq5"
    assert bridge["sha256"] == "08ba484a2f676a78e36b19d7632057e2c9a903ab0d526caa7c7a174ab0d16e5f"

    seq = next(item for item in manifest["files"] if item["role"] == "sequence_ea")
    assert seq["name"] == "InstitutionalSMC_SequenceEA_v3_33_SafetyPersistentOwner_Demo.mq5"
    source = ROOT / seq["path"]
    assert source.exists()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == seq["sha256"] == "9dba86a03f424273b632c347289aff4570a5a8e649be0694715968f9d9321fd9"

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
    }
    assert required.issubset(set(manifest["channel_features"]))
