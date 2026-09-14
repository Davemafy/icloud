from types import SimpleNamespace

from app.institutional_two_zone import (
    _attach_liquidity_to_marked_zone,
    _attached_liquidity,
    _build_full_candidate_pool,
    _compact_envelope,
    apply_two_zone_institutional_map,
    primary_zone_interacting,
)
from app.models import Analysis, Direction, Grade, LiquidityLevel, MarketSnapshot, Zone, ZoneState


def _zone(zid, direction, source_tf, low, high, grade=Grade.A, touches=0):
    required = "BSL_IN_MARKED_ZONE" if direction == Direction.SELL else "SSL_IN_MARKED_ZONE"
    return Zone(
        zone_id=zid,
        original_direction=direction,
        flip_direction=direction.opposite(),
        setup_type="CONTINUATION" if direction == Direction.SELL else "REVERSAL",
        source_tf=source_tf,
        grade=grade,
        state=ZoneState.ACTIVE,
        core_low=low,
        core_high=high,
        core_method=f"WATCH|{source_tf}_TEST",
        location_score=7.0,
        zone_low=low,
        zone_high=high,
        touch_count=touches,
        independent_confluence_count=4,
        confluences=["INSTITUTIONAL_DISPLACEMENT", "LIQUIDITY_IN_MARKED_ZONE", required],
        source_ts=100,
        invalidation_level=high if direction == Direction.SELL else low,
        invalidation_rule="test",
        clear_run=10.0,
    )


def _snapshot(mid=100.0):
    return MarketSnapshot(
        sent_at=1000,
        bid=mid - 0.1,
        ask=mid + 0.1,
        spread_points=20,
        point=0.01,
        atr_h1=10.0,
        atr_m15=2.0,
    )


def _analysis(zones, liquidity=None):
    if liquidity is None:
        liquidity = [
            LiquidityLevel(label="H4_BSL", price=110.8, side="ABOVE", source_tf="H4", distance=10.8),
            LiquidityLevel(label="H4_SSL", price=90.2, side="BELOW", source_tf="H4", distance=9.8),
        ]
    return Analysis(
        analysis_id="A1",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=zones,
        liquidity_map=liquidity,
        approved=True,
    )


def test_sell_requires_bsl_not_generic_nearby_liquidity():
    sell = _zone("S", Direction.SELL, "H1", 100.0, 101.0)
    a = _analysis(
        [sell],
        [
            LiquidityLevel(label="PSY", price=101.2, side="ABOVE", source_tf="PSY", distance=1.2),
            LiquidityLevel(label="H1_SSL", price=100.8, side="ABOVE", source_tf="H1", distance=0.8),
        ],
    )
    assert _attached_liquidity(sell, a, _snapshot()) is None


def test_buy_requires_ssl_not_bsl():
    buy = _zone("B", Direction.BUY, "H1", 99.0, 100.0)
    a = _analysis(
        [buy],
        [LiquidityLevel(label="H1_BSL", price=99.2, side="BELOW", source_tf="H1", distance=0.8)],
    )
    assert _attached_liquidity(buy, a, _snapshot()) is None


def test_attached_liquidity_is_physically_inside_marked_zone(monkeypatch):
    import app.institutional_two_zone as policy

    monkeypatch.setattr(policy, "atr", lambda bars: 2.0)
    sell = _zone("S", Direction.SELL, "H1", 100.0, 101.0)
    level = LiquidityLevel(label="H1_BSL", price=101.3, side="ABOVE", source_tf="H1", distance=1.3)
    _compact_envelope(sell, _snapshot())
    assert _attach_liquidity_to_marked_zone(sell, level, _snapshot()) is True
    assert sell.zone_low <= level.price <= sell.zone_high
    assert "LIQUIDITY_IN_MARKED_ZONE" in sell.confluences
    assert "BSL_IN_MARKED_ZONE" in sell.confluences


def test_public_map_keeps_h4_parents_ahead_of_nearer_h1(monkeypatch):
    import app.institutional_two_zone as policy

    zones = [
        _zone("H1_SELL", Direction.SELL, "H1", 103.0, 104.0, Grade.A_PLUS),
        _zone("H4_SELL", Direction.SELL, "H4", 110.0, 111.0, Grade.A, touches=1),
        _zone("H1_BUY", Direction.BUY, "H1", 96.0, 97.0, Grade.A_PLUS),
        _zone("H4_BUY", Direction.BUY, "H4", 90.0, 91.0, Grade.A),
    ]
    analysis = _analysis(zones)
    monkeypatch.setattr(policy, "_build_full_candidate_pool", lambda a, s: (zones, {}))

    selected = apply_two_zone_institutional_map(analysis, _snapshot())

    assert [z.zone_id for z in selected] == ["H4_SELL", "H4_BUY"]
    assert analysis.selected_zone_id == "H4_SELL"
    assert all(z.core_method.startswith("ARMED|") for z in selected)
    assert "Prompt-guided primary map" in analysis.trader_brief
    assert analysis.execution_policy["public_zone_map"]["sell_requires_bsl_in_marked_zone"] is True
    assert analysis.execution_policy["public_zone_map"]["buy_requires_ssl_in_marked_zone"] is True


def test_second_core_mitigation_is_rejected_from_candidate_pool(monkeypatch):
    import app.institutional_two_zone as policy

    sell = _zone("Z1", Direction.SELL, "H4", 100.0, 101.0, touches=2)
    a = _analysis([sell])
    candidate = SimpleNamespace(source_tf="H4")
    monkeypatch.setattr(policy, "_candidate_rows", lambda s: [("Z1", 1, candidate)])
    monkeypatch.setattr(policy, "_core_touches", lambda *args, **kwargs: 2)

    pool, _ = _build_full_candidate_pool(a, _snapshot())
    assert pool == []


def test_interacting_primary_is_marked_interacting_and_clears_armed_selection(monkeypatch):
    import app.institutional_two_zone as policy

    sell = _zone("H4_SELL", Direction.SELL, "H4", 100.0, 101.0, Grade.A)
    buy = _zone("H4_BUY", Direction.BUY, "H4", 90.0, 91.0, Grade.A)
    zones = [sell, buy]
    analysis = _analysis(zones)
    monkeypatch.setattr(policy, "_build_full_candidate_pool", lambda a, s: (zones, {}))
    monkeypatch.setattr(policy, "atr", lambda bars: 2.0)
    monkeypatch.setattr(policy, "evaluate_zone_state", lambda *args, **kwargs: ZoneState.ACTIVE)

    apply_two_zone_institutional_map(analysis, _snapshot(mid=101.4))

    assert analysis.zones[0].core_method.startswith("INTERACTING|")
    assert analysis.zones[1].core_method.startswith("ARMED|")
    assert analysis.selected_zone_id == ""


def test_primary_zone_interaction_requires_in_zone_liquidity(monkeypatch):
    import app.institutional_two_zone as policy

    monkeypatch.setattr(policy, "atr", lambda bars: 2.0)
    monkeypatch.setattr(policy, "evaluate_zone_state", lambda *args, **kwargs: ZoneState.ACTIVE)
    zone = _zone("Z1", Direction.SELL, "H4", 100.0, 101.0, Grade.A)
    assert primary_zone_interacting(zone, _snapshot(mid=101.4)) is True
    zone.confluences = ["INSTITUTIONAL_DISPLACEMENT"]
    assert primary_zone_interacting(zone, _snapshot(mid=101.4)) is False
