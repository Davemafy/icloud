from app.engine import Origin
from app.models import Direction, MarketSnapshot
from app.prompt_candidate_policy import build_prompt_candidates


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=1,
        bid=100.0,
        ask=100.2,
        spread_points=20.0,
        point=0.01,
        atr_h1=4.0,
        atr_m15=1.0,
    )


def test_h4_sweep_rejection_parent_is_kept_without_h1_overlap(monkeypatch):
    import app.prompt_candidate_policy as policy

    h4_sell = Origin(Direction.SELL, 109.0, 111.0, 100, "H4", 10, 2.2, False)

    def fake_origins(bars, tf, max_items=18):
        return [h4_sell] if tf == "H4" else []

    monkeypatch.setattr(policy, "prompt_origins", fake_origins)
    rows = build_prompt_candidates(_snapshot())

    assert len(rows) == 1
    assert rows[0].direction == Direction.SELL
    assert rows[0].source_tf == "H4"
    assert rows[0].low == 109.0
    assert rows[0].high == 111.0
    assert rows[0].method == "PROMPT_H4_PARENT_ORIGIN"


def test_h1_refines_matching_h4_parent(monkeypatch):
    import app.prompt_candidate_policy as policy

    h4_buy = Origin(Direction.BUY, 89.0, 92.0, 100, "H4", 10, 2.0, False)
    h1_buy = Origin(Direction.BUY, 90.0, 91.0, 110, "H1", 11, 2.4, True)

    def fake_origins(bars, tf, max_items=18):
        return [h4_buy] if tf == "H4" else [h1_buy]

    monkeypatch.setattr(policy, "prompt_origins", fake_origins)
    rows = build_prompt_candidates(_snapshot())

    refined = [row for row in rows if row.source_tf == "H4>H1"]
    assert len(refined) == 1
    assert refined[0].direction == Direction.BUY
    assert refined[0].low == 90.0
    assert refined[0].high == 91.0
    assert len(refined[0].components) == 2


def test_h1_is_fallback_when_no_h4_parent_exists(monkeypatch):
    import app.prompt_candidate_policy as policy

    h1_sell = Origin(Direction.SELL, 104.0, 105.0, 110, "H1", 11, 2.1, False)

    def fake_origins(bars, tf, max_items=18):
        return [] if tf == "H4" else [h1_sell]

    monkeypatch.setattr(policy, "prompt_origins", fake_origins)
    rows = build_prompt_candidates(_snapshot())

    assert len(rows) == 1
    assert rows[0].source_tf == "H1"
    assert rows[0].method == "PROMPT_H1_TACTICAL_FALLBACK"
