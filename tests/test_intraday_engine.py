from app import intraday_engine
from app.engine import Origin
from app.models import Direction, MarketSnapshot


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=1,
        bid=100.0,
        ask=100.2,
        spread_points=20.0,
        atr_h1=10.0,
        atr_m15=2.0,
    )


def test_tactical_candidates_use_h4_h1_only(monkeypatch):
    h4 = Origin(Direction.BUY, 90.0, 95.0, 10, "H4", 1, 2.2, True)
    h1 = Origin(Direction.BUY, 92.0, 94.0, 20, "H1", 2, 2.1, True)
    calls = []

    def fake_origins(_bars, tf, max_items=18):
        calls.append(tf)
        if tf == "H4":
            return [h4]
        if tf == "H1":
            return [h1]
        raise AssertionError(f"unexpected zone timeframe {tf}")

    monkeypatch.setattr(intraday_engine, "displacement_origins", fake_origins)
    candidates = intraday_engine.build_candidates(_snapshot())

    assert calls == ["H4", "H1"]
    assert len(candidates) == 1
    assert candidates[0].source_tf == "H4>H1"
    assert {x.tf for x in candidates[0].components} == {"H4", "H1"}


def test_zone_distance_prefers_nearby_intraday_area():
    assert intraday_engine._distance_to_zone(100.0, 99.0, 101.0) == 0.0
    assert intraday_engine._distance_to_zone(100.0, 90.0, 95.0) == 5.0
    assert intraday_engine._distance_to_zone(100.0, 105.0, 110.0) == 5.0
