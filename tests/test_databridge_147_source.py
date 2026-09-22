from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_47_ContextGradeRiskTruth.mq5"


def test_v147_sequence_338_truth_contract():
    bridge = BRIDGE.read_text(encoding="utf-8")
    assert '#property version "1.47"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.47"' in bridge
    assert '#define TZ_JOURNAL_BRIDGE_VERSION "1.47"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.38"' in bridge
    assert "TZ_SendHeartbeatV147" in bridge
    assert 'TZ_SendSnapshotCycle("V147_VERIFY")' in bridge
    assert "JournalContinuityResyncSeconds=180" in bridge
    assert "BackfillJournalHistory(true);" in bridge
    assert "TZ_RefreshPlanContextWithJournalContinuity()" in bridge
