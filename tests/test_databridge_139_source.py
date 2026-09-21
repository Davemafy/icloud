from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_39_JournalRecoveryTruth.mq5"
CORE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5"


def test_v139_reports_current_runtime_and_recovery_contract():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")

    assert '#property version "1.39"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.39"' in bridge
    assert '#define TZ_JOURNAL_BRIDGE_VERSION "1.39"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.34"' in bridge
    assert 'journal_history_backfill\\":true' in bridge
    assert 'BackfillJournalHistory(false);' in bridge
    assert 'TZ_SendHeartbeatV139();' in bridge

    for needle in [
        "EnableJournalHistoryBackfill",
        "JournalBackfillDays",
        "JournalBackfillEverySeconds",
        "BackfillJournalHistory",
        "SendJournalAt",
        "CanonicalTradeId",
        "EventUidDeal",
        "EventUidPosition",
        "HistoryDealsTotal()",
        "HistoryDealGetTicket(i)",
        "recovered_from_mt5_history",
    ]:
        assert needle in core


def test_v139_core_keeps_trade_lifecycle_recovery_read_only():
    core = CORE.read_text(encoding="utf-8")
    assert 'Post("/mt5/feedback",body,r)' in core
    assert "OrderSend(" not in core
    assert "trade.Buy(" not in core
    assert "trade.Sell(" not in core
