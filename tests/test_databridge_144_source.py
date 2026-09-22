from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_44_Sequence336Truth.mq5"
CORE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5"


def test_v144_sequence_336_truth_overlay_contract():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")

    assert '#property version "1.44"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.44"' in bridge
    assert '#define TZ_JOURNAL_BRIDGE_VERSION "1.44"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.36"' in bridge
    assert "TZ_SendHeartbeatV144();" in bridge
    assert 'TZ_SendSnapshotCycle("V144_VERIFY")' in bridge
    assert 'stage=="HANDOFF_CONFIRMATION"' in bridge
    assert '"ENTRY BLOCKED: MIN RR"' in bridge
    assert '"ENTRY BLOCKED: OBJECTIVE ALREADY TRADED"' in bridge

    assert "IsTester()" not in core
    assert "MQLInfoInteger(MQL_TESTER)" in core


def test_v144_remains_execution_read_only():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")
    for text in (bridge, core):
        assert "OrderSend(" not in text
        assert "trade.Buy(" not in text
        assert "trade.Sell(" not in text
