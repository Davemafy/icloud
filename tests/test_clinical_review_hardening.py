import json

from app import journal
from app.dashboard_view import compact_dashboard_html


def _row(event, ts, details, analysis_id="A1", zone_id="Z1", price=0.0):
    return {
        "id": ts,
        "ts": ts,
        "event": event,
        "analysis_id": analysis_id,
        "zone_id": zone_id,
        "price": price,
        "details": json.dumps(details),
    }


def test_ml_candidates_are_research_observations_not_trades(monkeypatch):
    rows = [
        _row(
            "ML_CANDIDATE",
            30,
            {
                "candidate_id": "CAND_1",
                "setup": "MOMENTUM_PULLBACK",
                "direction": "SELL",
            },
        )
    ]
    monkeypatch.setattr(journal, "recent_feedback", lambda limit=5000: rows)

    assert journal.build_trades() == []
    perf = journal.performance_summary()
    assert perf["trade_count"] == 0
    assert perf["closed_trades"] == 0
    assert perf["win_rate"] is None
    assert perf["research_observations"] == 1
    assert perf["unique_research_observations"] == 1


def test_real_position_lifecycle_builds_one_closed_trade(monkeypatch):
    trade_id = "A1|Z1|P0"
    rows = [
        _row(
            "TRADE_CLOSED",
            30,
            {
                "trade_id": trade_id,
                "position_id": 777,
                "setup": "PRIMARY",
                "bridge_version": "1.35",
                "sequence_version": "3.25",
            },
            price=101.5,
        ),
        _row(
            "TP_HIT",
            20,
            {
                "trade_id": trade_id,
                "position_id": 777,
                "setup": "PRIMARY",
                "direction": "BUY",
                "net_profit": 12.5,
            },
            price=101.5,
        ),
        _row(
            "ENTRY_OPENED",
            10,
            {
                "trade_id": trade_id,
                "position_id": 777,
                "setup": "PRIMARY",
                "direction": "BUY",
                "grade": "A+",
                "volume": 0.01,
            },
            price=100.0,
        ),
    ]
    monkeypatch.setattr(journal, "recent_feedback", lambda limit=5000: rows)

    trades = journal.build_trades()
    assert len(trades) == 1
    trade = trades[0]
    assert trade["status"] == "CLOSED"
    assert trade["direction"] == "BUY"
    assert trade["pnl"] == 12.5
    assert trade["entry_price"] == 100.0
    assert trade["exit_price"] == 101.5
    assert trade["display_id"] == "PRIMARY · POS 777"

    perf = journal.performance_summary()
    assert perf["trade_count"] == 1
    assert perf["closed_trades"] == 1
    assert perf["wins"] == 1
    assert perf["win_rate"] == 100.0


def test_dashboard_labels_are_clinically_unambiguous_and_read_only():
    html = (
        '<div class="card"><h3>Stable release</h3></div>'
        '<h2>Rejected Zone Diagnostics</h2><table><thead><tr><th>Distance H1 ATR</th></tr></thead></table>'
        '<h2>Live trading journal <span>auto-updates every 3s</span></h2>'
        '<div class="card"><h3>Recorded trades</h3></div>'
        '<script>'
        "let currentJournal=null;"
        "$('winRate').textContent=num(d.win_rate,1)+'%';"
        "const row=`<b>${esc(x.trade_id)}</b>`;"
        '</script></body>'
    )

    cleaned = compact_dashboard_html(html)

    assert "MT5 stable package" in cleaned
    assert "Executed trades" in cleaned
    assert "Distance (× H1 ATR)" in cleaned
    assert "dashboard refreshes every 3s" in cleaned
    assert 'id="selectedZoneAudit"' in cleaned
    assert "Cloud application versions and MT5 stable-package releases are separate namespaces" in cleaned
    assert "display_id||x.trade_id" in cleaned
    assert "ML_CANDIDATE remains research telemetry and is not a trade" in cleaned
    assert "/mt5/plan" not in cleaned
    assert "OrderSend" not in cleaned
    assert "WebRequest" not in cleaned
