from app import journal


def test_current_sequence_tags_recover_setup_names_from_legacy_unknown_payloads():
    cases = {
        "P0": "PRIMARY",
        "R1": "REENTRY_1",
        "R2": "REENTRY_2",
        "F0": "ZONE_FLIP",
        "FR1": "FLIP_REENTRY_1",
        "FR2": "FLIP_REENTRY_2",
        "S0": "ZONE_SWEEP_CONTINUATION",
        "L0": "LIQUIDITY_REVERSAL",
        "C0": "CONTINUATION_RESCUE",
        "E0": "ESCAPE_PULLBACK",
    }
    for tag, expected in cases.items():
        assert journal._canonical_setup({"setup": "UNKNOWN", "tag": tag}) == expected
        assert journal._canonical_setup({"setup": "UNKNOWN", "comment": f"SMCV6 {tag} T1"}) == expected


def test_build_trades_relabels_legacy_unknown_liquidity_reversal(monkeypatch):
    rows = [
        {
            "ts": 20,
            "event": "TRADE_CLOSED",
            "analysis_id": "A1",
            "zone_id": "Z1",
            "price": 100.0,
            "details": {
                "trade_id": "A1|Z1|L0",
                "setup": "UNKNOWN",
                "tag": "L0",
                "comment": "SMCV6 L0 T1",
                "bridge_version": "1.31",
                "sequence_version": "3.32",
            },
        },
        {
            "ts": 10,
            "event": "ENTRY_OPENED",
            "analysis_id": "A1",
            "zone_id": "Z1",
            "price": 101.0,
            "details": {
                "trade_id": "A1|Z1|L0",
                "setup": "UNKNOWN",
                "tag": "L0",
                "direction": "SELL",
                "grade": "A+",
                "comment": "SMCV6 L0 T1",
            },
        },
    ]
    monkeypatch.setattr(journal, "recent_feedback", lambda limit=5000: rows)
    trade = journal.build_trades()[0]
    assert trade["setup"] == "LIQUIDITY_REVERSAL"
