from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_40_OverlayTruth.mq5"
CORE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5"


def test_v140_chart_overlay_reports_sequence_truth_not_no_trade():
    bridge = BRIDGE.read_text(encoding="utf-8")

    assert '#property version "1.40"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.40"' in bridge
    assert '#define TZ_JOURNAL_BRIDGE_VERSION "1.40"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.34"' in bridge
    assert "TZ_SequenceExecutionDisplay" in bridge
    assert "WAITING FOR VALUE / RETRACE" in bridge
    assert "WAITING FOR SEQUENCE AUTHORITY" in bridge
    assert "SMC Cloud | EXECUTION:" in bridge
    assert '" | POSITIONS "' in bridge
    assert 'status+="\\nSMC Cloud | MAP "' in bridge
    assert "TZ_ClearLegacyExecutionOverlay" in bridge
    assert 'StringFind(text,"SMC Cloud | NO_TRADE")>=0' in bridge
    assert 'StringFind(text,"zones 0")>=0' in bridge
    assert "TZ_SendHeartbeatV140();" in bridge


def test_v140_remains_read_only_and_preserves_journal_recovery():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")

    assert "BackfillJournalHistory(false);" in bridge
    assert 'journal_history_backfill\\":true' in bridge
    assert "OrderSend(" not in bridge
    assert "trade.Buy(" not in bridge
    assert "trade.Sell(" not in bridge

    for needle in [
        "EnableJournalHistoryBackfill",
        "CanonicalTradeId",
        "EventUidDeal",
        "EventUidPosition",
        "HistoryDealsTotal()",
        "recovered_from_mt5_history",
    ]:
        assert needle in core
