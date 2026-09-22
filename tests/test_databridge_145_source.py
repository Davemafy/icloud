from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_45_JournalContinuity.mq5"
CORE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5"


def test_v145_journal_continuity_contract():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")

    assert '#property version "1.45"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.45"' in bridge
    assert '#define TZ_JOURNAL_BRIDGE_VERSION "1.45"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.36"' in bridge
    assert "JournalContinuityResyncSeconds=180" in bridge
    assert "TZ_RefreshPlanContextWithJournalContinuity()" in bridge
    assert "previousCloudVersion!=g_cloudVersion" in bridge
    assert "BackfillJournalHistory(true);" in bridge
    assert 'TZ_SendSnapshotCycle("V145_VERIFY")' in bridge
    assert "TZ_SendHeartbeatV145();" in bridge

    # Recovery remains sourced from MT5 history and cloud-side event_uid dedupe.
    assert "BackfillJournalHistory(bool force=false)" in core
    assert "EventUidDeal" in core
    assert "EventUidPosition" in core


def test_v145_remains_execution_read_only():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")
    for text in (bridge, core):
        assert "OrderSend(" not in text
        assert "trade.Buy(" not in text
        assert "trade.Sell(" not in text
