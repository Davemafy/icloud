from pathlib import Path


EXPORTER = Path("mt5/backtest/TradeZone_MasterSniper_HistoryExporter.mq5")


def test_history_exporter_is_no_trading_and_exports_required_files():
    text = EXPORTER.read_text(encoding="utf-8")
    for forbidden in ("OrderSend(", "trade.Buy(", "trade.Sell(", "CTrade "):
        assert forbidden not in text
    for name in (
        "XAU_D1.csv",
        "XAU_H4.csv",
        "XAU_H1.csv",
        "XAU_M15.csv",
        "XAU_M1.csv",
        "DXY_D1.csv",
        "DXY_H4.csv",
        "DXY_H1.csv",
        "news.csv",
        "export_manifest.txt",
    ):
        assert name in text
    assert "CalendarValueHistory" in text
    assert "CalendarEventById" in text
    assert "HISTORY_EXPORT PASS OVERALL" in text
    assert "NO ORDERS WERE SENT" in text


def test_history_exporter_has_timeframe_specific_warmup():
    text = EXPORTER.read_text(encoding="utf-8")
    for required in (
        "if(tf==PERIOD_D1)days=500;",
        "else if(tf==PERIOD_H4)days=180;",
        "else if(tf==PERIOD_H1)days=60;",
        "else if(tf==PERIOD_M15)days=15;",
        "else if(tf==PERIOD_M1)days=2;",
    ):
        assert required in text
