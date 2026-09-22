from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_46_GradeRiskTruth.mq5"
CORE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5"


def test_v146_sequence_337_truth_contract():
    bridge = BRIDGE.read_text(encoding="utf-8")
    assert '#property version "1.46"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.46"' in bridge
    assert '#define TZ_JOURNAL_BRIDGE_VERSION "1.46"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.37"' in bridge
    assert "TZ_SendHeartbeatV146" in bridge
    assert 'TZ_SendSnapshotCycle("V146_VERIFY")' in bridge
    assert "JournalContinuityResyncSeconds=180" in bridge


def test_v146_remains_execution_read_only():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")
    for text in (bridge, core):
        assert "OrderSend(" not in text
        assert "trade.Buy(" not in text
        assert "trade.Sell(" not in text
