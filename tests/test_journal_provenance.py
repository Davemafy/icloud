import json

from app import journal
from app import journal_provenance


def _row(event, ts, details, *, analysis_id="A1", zone_id="Z1", price=0.0, row_id=None):
    return {
        "id": row_id if row_id is not None else ts,
        "ts": ts,
        "event": event,
        "analysis_id": analysis_id,
        "zone_id": zone_id,
        "price": price,
        "details": json.dumps(details),
    }


def test_recovery_unknown_never_overwrites_stronger_live_metadata(monkeypatch):
    rows = [
        _row(
            "ENTRY_OPENED",
            10,
            {
                "event_uid": "ENTRY_OPENED|DEAL|1",
                "trade_id": "MT5POS|1|777",
                "campaign_id": "A1|Z1|L0",
                "position_id": 777,
                "deal_id": 1,
                "setup": "LIQUIDITY_REVERSAL",
                "tag": "L0",
                "direction": "SELL",
                "grade": "A+",
                "bridge_version": "1.39",
                "sequence_version": "3.34",
            },
            price=100.0,
        ),
        _row(
            "POSITION_EXIT",
            20,
            {
                "event_uid": "POSITION_EXIT|DEAL|2",
                "trade_id": "MT5POS|1|777",
                "campaign_id": "MT5_HISTORY||UNKNOWN",
                "position_id": 777,
                "deal_id": 2,
                "setup": "UNKNOWN",
                "tag": "UNKNOWN",
                "net_profit": 5.0,
                "recovered_from_mt5_history": True,
                # Legacy 1.40 payload: these are the recovery runtime, not execution versions.
                "bridge_version": "1.40",
                "sequence_version": "3.34",
            },
            analysis_id="MT5_HISTORY",
            zone_id="",
            price=95.0,
        ),
        _row(
            "TRADE_CLOSED",
            20,
            {
                "event_uid": "TRADE_CLOSED|POSITION|777",
                "trade_id": "MT5POS|1|777",
                "position_id": 777,
                "setup": "UNKNOWN",
                "recovered_from_mt5_history": True,
                "bridge_version": "1.40",
                "sequence_version": "3.34",
            },
            analysis_id="MT5_HISTORY",
            zone_id="",
            price=95.0,
            row_id=30,
        ),
    ]
    monkeypatch.setattr(journal, "recent_feedback", lambda limit=5000: rows)

    trade = journal_provenance.build_trades()[0]
    assert trade["setup"] == "LIQUIDITY_REVERSAL"
    assert trade["grade"] == "A+"
    assert trade["analysis_id"] == "A1"
    assert trade["zone_id"] == "Z1"
    assert trade["campaign_id"] == "A1|Z1|L0"
    assert trade["execution_bridge_version"] == "1.39"
    assert trade["execution_sequence_version"] == "3.34"
    assert trade["recovery_bridge_version"] == "1.40"
    assert trade["recovery_sequence_version"] == "3.34"
    assert trade["history_recovered"] is True


def test_history_only_positions_are_labeled_unclassified_not_falsely_inferred(monkeypatch):
    rows = [
        _row(
            "ENTRY_OPENED",
            10,
            {
                "event_uid": "ENTRY_OPENED|DEAL|1",
                "trade_id": "MT5POS|1|777",
                "position_id": 777,
                "deal_id": 1,
                "setup": "UNKNOWN",
                "tag": "UNKNOWN",
                "direction": "SELL",
                "recovered_from_mt5_history": True,
                "bridge_version": "1.40",
                "sequence_version": "3.34",
            },
            analysis_id="MT5_HISTORY",
            zone_id="",
            price=100.0,
        ),
        _row(
            "TRADE_CLOSED",
            20,
            {
                "event_uid": "TRADE_CLOSED|POSITION|777",
                "trade_id": "MT5POS|1|777",
                "position_id": 777,
                "setup": "UNKNOWN",
                "recovered_from_mt5_history": True,
            },
            analysis_id="MT5_HISTORY",
            zone_id="",
            price=99.0,
        ),
    ]
    monkeypatch.setattr(journal, "recent_feedback", lambda limit=5000: rows)

    trade = journal_provenance.build_trades()[0]
    assert trade["setup"] == "UNCLASSIFIED_HISTORY"
    assert trade["grade"] == "UNCLASSIFIED_HISTORY"
    assert trade["setup_provenance"] == "UNAVAILABLE_FROM_MT5_HISTORY"
    assert trade["execution_bridge_version"] == ""
    assert trade["recovery_bridge_version"] == "1.40"


def test_simultaneous_mt5_legs_group_into_one_execution_burst(monkeypatch):
    rows = []
    for pid, entry, pnl in [
        (101, 100.00, 10.0),
        (102, 100.04, 15.0),
        (103, 100.04, 0.0),
    ]:
        rows.extend(
            [
                _row(
                    "ENTRY_OPENED",
                    100,
                    {
                        "event_uid": f"ENTRY_OPENED|DEAL|{pid}1",
                        "trade_id": f"MT5POS|1|{pid}",
                        "position_id": pid,
                        "deal_id": int(f"{pid}1"),
                        "setup": "UNKNOWN",
                        "direction": "SELL",
                        "recovered_from_mt5_history": True,
                    },
                    analysis_id="MT5_HISTORY",
                    zone_id="",
                    price=entry,
                    row_id=pid * 10,
                ),
                _row(
                    "POSITION_EXIT",
                    200 + pid,
                    {
                        "event_uid": f"POSITION_EXIT|DEAL|{pid}2",
                        "trade_id": f"MT5POS|1|{pid}",
                        "position_id": pid,
                        "deal_id": int(f"{pid}2"),
                        "net_profit": pnl,
                        "recovered_from_mt5_history": True,
                    },
                    analysis_id="MT5_HISTORY",
                    zone_id="",
                    price=95.0,
                    row_id=pid * 10 + 1,
                ),
                _row(
                    "TRADE_CLOSED",
                    200 + pid,
                    {
                        "event_uid": f"TRADE_CLOSED|POSITION|{pid}",
                        "trade_id": f"MT5POS|1|{pid}",
                        "position_id": pid,
                        "recovered_from_mt5_history": True,
                    },
                    analysis_id="MT5_HISTORY",
                    zone_id="",
                    price=95.0,
                    row_id=pid * 10 + 2,
                ),
            ]
        )

    # A distinct entry four seconds later must not be merged.
    rows.extend(
        [
            _row(
                "ENTRY_OPENED",
                104,
                {
                    "event_uid": "ENTRY_OPENED|DEAL|2011",
                    "trade_id": "MT5POS|1|201",
                    "position_id": 201,
                    "deal_id": 2011,
                    "setup": "UNKNOWN",
                    "direction": "SELL",
                    "recovered_from_mt5_history": True,
                },
                analysis_id="MT5_HISTORY",
                zone_id="",
                price=100.02,
                row_id=2010,
            ),
            _row(
                "POSITION_EXIT",
                220,
                {
                    "event_uid": "POSITION_EXIT|DEAL|2012",
                    "trade_id": "MT5POS|1|201",
                    "position_id": 201,
                    "deal_id": 2012,
                    "net_profit": -5.0,
                    "recovered_from_mt5_history": True,
                },
                analysis_id="MT5_HISTORY",
                zone_id="",
                price=101.0,
                row_id=2011,
            ),
            _row(
                "TRADE_CLOSED",
                220,
                {
                    "event_uid": "TRADE_CLOSED|POSITION|201",
                    "trade_id": "MT5POS|1|201",
                    "position_id": 201,
                    "recovered_from_mt5_history": True,
                },
                analysis_id="MT5_HISTORY",
                zone_id="",
                price=101.0,
                row_id=2012,
            ),
        ]
    )
    monkeypatch.setattr(journal, "recent_feedback", lambda limit=5000: rows)

    positions = journal_provenance.build_trades()
    executions = journal_provenance.build_execution_groups(positions)
    assert len(positions) == 4
    assert len(executions) == 2

    burst = next(x for x in executions if x["position_count"] == 3)
    assert burst["grouping_provenance"] == "RECONSTRUCTED_ENTRY_BURST"
    assert burst["pnl"] == 25.0


def test_performance_is_execution_level_while_preserving_position_count(monkeypatch):
    rows = []
    for pid, pnl in [(101, 10.0), (102, -2.0), (103, 0.0)]:
        rows.extend(
            [
                _row(
                    "ENTRY_OPENED",
                    100,
                    {
                        "event_uid": f"ENTRY_OPENED|DEAL|{pid}1",
                        "trade_id": f"MT5POS|1|{pid}",
                        "position_id": pid,
                        "deal_id": int(f"{pid}1"),
                        "setup": "UNKNOWN",
                        "direction": "SELL",
                        "recovered_from_mt5_history": True,
                    },
                    analysis_id="MT5_HISTORY",
                    zone_id="",
                    price=100.0,
                    row_id=pid * 10,
                ),
                _row(
                    "POSITION_EXIT",
                    200,
                    {
                        "event_uid": f"POSITION_EXIT|DEAL|{pid}2",
                        "trade_id": f"MT5POS|1|{pid}",
                        "position_id": pid,
                        "deal_id": int(f"{pid}2"),
                        "net_profit": pnl,
                        "recovered_from_mt5_history": True,
                    },
                    analysis_id="MT5_HISTORY",
                    zone_id="",
                    price=95.0,
                    row_id=pid * 10 + 1,
                ),
                _row(
                    "TRADE_CLOSED",
                    200,
                    {
                        "event_uid": f"TRADE_CLOSED|POSITION|{pid}",
                        "trade_id": f"MT5POS|1|{pid}",
                        "position_id": pid,
                        "recovered_from_mt5_history": True,
                    },
                    analysis_id="MT5_HISTORY",
                    zone_id="",
                    price=95.0,
                    row_id=pid * 10 + 2,
                ),
            ]
        )
    monkeypatch.setattr(journal, "recent_feedback", lambda limit=5000: rows)

    perf = journal_provenance.performance_summary()
    assert perf["position_count"] == 3
    assert perf["closed_positions"] == 3
    assert perf["execution_count"] == 1
    assert perf["closed_executions"] == 1
    assert perf["execution_win_rate"] == 100.0
    assert perf["net_demo_pnl"] == 8.0


def test_live_runtime_mark_does_not_rewrite_original_execution_provenance(monkeypatch):
    rows = [
        _row(
            "ENTRY_OPENED",
            100,
            {
                "event_uid": "ENTRY_OPENED|DEAL|1001",
                "trade_id": "MT5POS|1|100",
                "position_id": 100,
                "deal_id": 1001,
                "setup": "REENTRY_1",
                "tag": "R1",
                "direction": "SELL",
                "recovered_from_mt5_history": True,
                "metadata_source": "MT5_COMMENT",
                "recovery_bridge_version": "1.42",
                "recovery_sequence_version": "3.34",
            },
            analysis_id="MT5_HISTORY",
            zone_id="",
            price=100.0,
        ),
        _row(
            "POSITION_MARK",
            200,
            {
                "trade_id": "MT5POS|1|100",
                "campaign_id": "A_NEW|Z_NEW|R1",
                "position_id": 100,
                "setup": "REENTRY_1",
                "tag": "R1",
                "direction": "SELL",
                "grade": "A+",
                "entry_price": 100.0,
                "metadata_source": "LIVE_RUNTIME_CONTEXT",
                "execution_bridge_version": "1.42",
                "execution_sequence_version": "3.34",
                "execution_cloud_version": "6.5.42",
            },
            analysis_id="A_NEW",
            zone_id="Z_NEW",
            price=95.0,
            row_id=2000,
        ),
    ]
    monkeypatch.setattr(journal, "recent_feedback", lambda limit=5000: rows)

    trade = journal_provenance.build_trades()[0]
    assert trade["campaign_id"] == ""
    assert trade["analysis_id"] == "MT5_HISTORY"
    assert trade["zone_id"] == ""
    assert trade["grade"] == "UNCLASSIFIED_HISTORY"
    assert trade["execution_bridge_version"] == ""
    assert trade["execution_sequence_version"] == ""
    assert trade["execution_cloud_version"] == ""
    assert trade["recovery_bridge_version"] == "1.42"
    assert trade["recovery_sequence_version"] == "3.34"


def test_partial_multi_leg_execution_remains_one_open_execution(monkeypatch):
    rows = [
        _row(
            "ENTRY_OPENED",
            100,
            {
                "event_uid": "ENTRY_OPENED|DEAL|1011",
                "trade_id": "MT5POS|1|101",
                "position_id": 101,
                "deal_id": 1011,
                "setup": "REENTRY_1",
                "tag": "R1",
                "direction": "SELL",
                "recovered_from_mt5_history": True,
                "metadata_source": "MT5_COMMENT",
            },
            analysis_id="MT5_HISTORY",
            zone_id="",
            price=100.00,
            row_id=1010,
        ),
        _row(
            "ENTRY_OPENED",
            100,
            {
                "event_uid": "ENTRY_OPENED|DEAL|1021",
                "trade_id": "MT5POS|1|102",
                "position_id": 102,
                "deal_id": 1021,
                "setup": "REENTRY_1",
                "tag": "R1",
                "direction": "SELL",
                "recovered_from_mt5_history": True,
                "metadata_source": "MT5_COMMENT",
            },
            analysis_id="MT5_HISTORY",
            zone_id="",
            price=100.20,
            row_id=1020,
        ),
        _row(
            "SL_HIT",
            200,
            {
                "event_uid": "SL_HIT|DEAL|1022",
                "trade_id": "MT5POS|1|102",
                "position_id": 102,
                "deal_id": 1022,
                "setup": "REENTRY_1",
                "tag": "R1",
                "net_profit": 7.0,
            },
            analysis_id="",
            zone_id="",
            price=95.0,
            row_id=1021,
        ),
        _row(
            "TRADE_CLOSED",
            200,
            {
                "event_uid": "TRADE_CLOSED|POSITION|102",
                "trade_id": "MT5POS|1|102",
                "position_id": 102,
                "setup": "REENTRY_1",
                "tag": "R1",
            },
            analysis_id="",
            zone_id="",
            price=95.0,
            row_id=1022,
        ),
        _row(
            "POSITION_MARK",
            210,
            {
                "trade_id": "MT5POS|1|101",
                "campaign_id": "A_CURRENT|Z_CURRENT|R1",
                "position_id": 101,
                "setup": "REENTRY_1",
                "tag": "R1",
                "direction": "SELL",
                "grade": "A+",
                "entry_price": 100.00,
                "metadata_source": "LIVE_RUNTIME_CONTEXT",
                "execution_bridge_version": "1.42",
                "execution_sequence_version": "3.34",
                "execution_cloud_version": "6.5.42",
            },
            analysis_id="A_CURRENT",
            zone_id="Z_CURRENT",
            price=96.0,
            row_id=1011,
        ),
    ]
    monkeypatch.setattr(journal, "recent_feedback", lambda limit=5000: rows)

    positions = journal_provenance.build_trades()
    executions = journal_provenance.build_execution_groups(positions)
    assert len(positions) == 2
    assert len(executions) == 1
    assert executions[0]["position_count"] == 2
    assert executions[0]["status"] == "OPEN"
    assert executions[0]["pnl"] == 7.0
    assert executions[0]["grouping_provenance"] == "RECONSTRUCTED_ENTRY_BURST"

    perf = journal_provenance.performance_summary()
    assert perf["execution_count"] == 1
    assert perf["closed_executions"] == 0
    assert perf["net_demo_pnl"] == 7.0
    assert perf["realized_position_pnl"] == 7.0
    assert perf["closed_execution_pnl"] == 0
