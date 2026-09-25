from pathlib import Path

from app.dashboard_view import compact_dashboard_html


def test_dashboard_injects_read_only_sniper_validation_ledger():
    raw = '<html><body><h2>Live trading journal</h2></body></html>'
    out = compact_dashboard_html(raw)
    assert 'id="sniperValidationLedger"' in out
    assert 'Master Sniper validation ledger' in out
    assert 'OBSERVATION ONLY' in out
    assert "fetch('/validation/sniper-ledger?limit=30'" in out
    assert 'descriptive only' in out
    assert 'cannot create a zone' in out
    assert 'id="sniper-validation-ledger-script"' in out


def test_validation_ledger_module_is_not_an_execution_path():
    text = Path("app/sniper_validation_ledger.py").read_text(encoding="utf-8")
    for forbidden in (
        "OrderSend",
        "trade.Buy",
        "trade.Sell",
        "execution_authority=",
        "save_analysis(",
        "save_feedback(",
        "active_plan_text(",
    ):
        assert forbidden not in text
    assert "OBSERVATION_ONLY_NO_EXECUTION_EFFECT" in text


def test_validation_endpoint_is_read_only_get():
    text = Path("app/main.py").read_text(encoding="utf-8")
    assert '@app.get("/validation/sniper-ledger")' in text
    assert "return build_validation_ledger(limit)" in text
