from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_43_Sequence335Truth.mq5"
CORE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5"


def test_v143_sequence_335_truth_overlay_contract():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")

    assert '#property version "1.43"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.43"' in bridge
    assert '#define TZ_JOURNAL_BRIDGE_VERSION "1.43"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.35"' in bridge
    assert "TZ_SendHeartbeatV143();" in bridge
    assert 'TZ_SendSnapshotCycle("V143_VERIFY")' in bridge
    assert 'stage=="REENTRY_CONFIRMATION"' in bridge
    assert '"WAITING FOR CLOSED M1 VALUE REACTION"' in bridge
    assert 'stage=="THESIS"' in bridge
    assert '"THESIS ENTRY LIMIT REACHED"' in bridge

    assert "IsTester()" not in core
    assert "MQLInfoInteger(MQL_TESTER)" in core


def test_v143_remains_execution_read_only():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")
    for text in (bridge, core):
        assert "OrderSend(" not in text
        assert "trade.Buy(" not in text
        assert "trade.Sell(" not in text
