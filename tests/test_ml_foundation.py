from app.ml_foundation import _bar_excursions, _barrier_hits, _candidate_key, _sanitize_features


def test_candidate_key_is_deterministic():
    assert _candidate_key("A", 1, "BUY") == _candidate_key("A", 1, "BUY")
    assert _candidate_key("A", 1, "BUY") != _candidate_key("A", 1, "SELL")


def test_feature_sanitizer_blocks_future_labels():
    raw = {
        "atr": 2.5,
        "regime": "TREND",
        "future_return": 10,
        "label_win": 1,
        "mfe_r": 3.0,
        "nested": {"spread": 20, "sl_hit": True},
    }
    clean = _sanitize_features(raw)
    assert clean["atr"] == 2.5
    assert clean["regime"] == "TREND"
    assert "future_return" not in clean
    assert "label_win" not in clean
    assert "mfe_r" not in clean
    assert clean["nested"] == {"spread": 20}


def test_buy_and_sell_excursions_are_directional():
    assert _bar_excursions("BUY", 100, 103, 98) == (3, 2)
    assert _bar_excursions("SELL", 100, 103, 98) == (2, 3)


def test_same_bar_tp_and_sl_is_detectable_as_ambiguous():
    sl, targets = _barrier_hits("BUY", high=105, low=95, stop=97, targets=[104, 110, 120])
    assert sl is True
    assert targets == [True, False, False]
