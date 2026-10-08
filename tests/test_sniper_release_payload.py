import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEQ = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_78_OwnerStableCampaigns_Demo.mq5"
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_59_DisplayTruth.mq5"
INCLUDE = ROOT / "mt5/stable/SniperContractParityV1.mqh"
RENDERER = ROOT / "mt5/stable/TradeZone_ZoneRenderer_v1_0.mqh"
JOURNAL_CORE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_33_StrategicEntryJournal.mq5"
MANIFEST = ROOT / "mt5/stable/manifest.json"

EXPECTED = {
    SEQ: "AUTO_FROM_MANIFEST",
    BRIDGE: "d4625df0bacae7af1f5e565041fed0e8974ae257bc9443897f7efc910b5c93f5",
    INCLUDE: "5002ee0c56900ed1baee056ed4cba882f1a99627824ccf399ecdf3ac24a4eee0",
    RENDERER: "06b0b4a2d07c9acbd31a237d27826ea804c63983994e61ac003c02b7b9e92442",
    JOURNAL_CORE: "7063db3f717eca0cd6c184a5a0ee74d70e2bad78308e52cb75822d32bfdfbdd0",
}


def test_release_payload_hashes_are_frozen():
    for path, expected in EXPECTED.items():
        if expected == "AUTO_FROM_MANIFEST":
            expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"][1]["sha256"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_release_payload_versions_and_parity_wiring():
    seq = SEQ.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")
    inc = INCLUDE.read_text(encoding="utf-8")
    assert '#property version   "3.78"' in seq
    assert '#define TZ_SEQUENCE_VERSION "3.78"' in seq
    assert '#include <TradeZoneCore\\SniperContractParityV1.mqh>' in seq
    assert 'TZ_PreCoreSync();ManagePositions();Evaluate();' in seq
    assert seq.index("ManagePositions();") < seq.index("Evaluate();")
    assert "M15_ACCEPTED_INVALIDATION_OWNER_SUSPENDED" in seq
    assert "BREAKOUT_DIRECTION_CONFLICT" in seq
    assert "TZ28_EvaluateAcceptedFlip();" in seq
    assert 'OrderFlowProxyMode=1' in seq
    assert 'CFD_TICK_VOLUME_PROXY' in seq
    assert 'TZ67_EvaluateOrderFlowProxy' in seq
    assert 'orderflow_proxy_state' in seq
    assert 'TZ69_FindProtectedSwing' in seq
    assert 'TZ69_ProtectedSwingExecutionStop' in seq
    assert 'last_candidate_rr_required' in seq
    assert 'last_candidate_swing_level' in seq
    assert 'M1_PROTECTED_SWING_HIGH' in seq
    assert 'M1_PROTECTED_SWING_LOW' in seq
    assert 'TZ70_BuildEngulfingRetest' in seq
    assert 'ZONE_ENGULFING_RETEST' in seq
    assert 'ReacquisitionSweepWindowBars=90' in seq
    assert 'ReacquisitionSweepToMssMaxBars=45' in seq
    assert 'opportunity_slot' in seq
    assert 'trace_sweep_reject_reason' in seq
    assert 'execution_context_type' in seq
    assert 'execution_context_source_zone_id' in seq
    assert 'execution_context_contract_verified' in seq
    assert 'TZ73_ReentryFreshEpochValid' in seq
    assert 'TZ73_OriginalZoneReentryLocationValid' in seq
    assert 'REENTRY_ORIGINAL_ZONE_MODEL_BEYOND_DISTAL_BOUNDARY' in seq
    assert '#property version "1.59"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.59"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "' in bridge
    assert 'HISTORICAL INVALIDATED ' in bridge
    assert 'ACTIVE ACCEPTED ' in bridge
    assert 'NO CURRENT M1 AUTHORITY' in bridge
    assert 'Sequence ",TZ_SEQUENCE_EXPECTED," execution-context display truth' in bridge
    assert 'TZ_SNIPER_PARITY_VERSION "SNIPER_PARITY_V1"' in inc


def test_release_manifest_promotes_exact_parity_payload():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["release"] == "6.4.20"
    assert manifest["ref"] == "0970a530f4aed1c40c44de299cb8e8bd9f195f12"
    assert manifest["data_bridge_version"] == "1.59"
    assert manifest["sequence_ea_version"] == "3.78"
    files = {item["role"]: item for item in manifest["files"]}
    assert files["data_bridge"]["sha256"] == EXPECTED[BRIDGE]
    assert files["sequence_ea"]["sha256"] == hashlib.sha256(SEQ.read_bytes()).hexdigest()
    supports = {item["role"]: item for item in manifest["support_files"]}
    assert supports["sniper_contract_parity"]["sha256"] == EXPECTED[INCLUDE]
    assert supports["zone_renderer"]["sha256"] == EXPECTED[RENDERER]
    assert supports["data_bridge_core"]["sha256"] == EXPECTED[JOURNAL_CORE]
    assert supports["sniper_contract_parity"]["target"] == "Include\\TradeZoneCore"



def test_sequence_378_runtime_truth_and_installer_contract():
    seq = SEQ.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    installer = (ROOT / "mt5/installer/Install_TradeZone_MT5.ps1").read_text(encoding="utf-8")
    assert '#property version   "3.78"' in seq
    assert '#define TZ_SEQUENCE_VERSION "3.78"' in seq
    assert "sequence_378_runtime_version_truth_hotfix" in manifest["channel_features"]
    assert "installer_12_verified_disk_version_truth" in manifest["channel_features"]
    assert "installed_sequence_version='+[string]$m.sequence_ea_version" in installer
    assert "'result=INSTALLED_REATTACH_REQUIRED'" in installer
    assert "FRONT_FACING_MANUAL_INSTALLER_1.3" in installer
