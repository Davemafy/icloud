from app.institutional_two_zone import apply_two_zone_institutional_map, primary_zone_interacting
from app.models import Analysis, Direction, Grade, LiquidityLevel, MarketSnapshot, Zone, ZoneState


def _zone(zid, direction, source_tf, low, high, grade=Grade.A, touches=0):
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
        independent_confluence_count=2,
        confluences=["INSTITUTIONAL_DISPLACEMENT"],
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


def test_public_map_keeps_only_best_h4_buy_and_sell(monkeypatch):
    import app.institutional_two_zone as policy

    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 0)
    monkeypatch.setattr(policy, "_candidate_map", lambda s: {})

    zones = [
        _zone("H1_SELL", Direction.SELL, "H1", 103.0, 104.0, Grade.A_PLUS),
        _zone("H4_SELL", Direction.SELL, "H4", 110.0, 111.0, Grade.B_PLUS),
        _zone("H1_BUY", Direction.BUY, "H1", 96.0, 97.0, Grade.A_PLUS),
        _zone("H4_BUY", Direction.BUY, "H4", 90.0, 91.0, Grade.B_PLUS),
    ]
    analysis = Analysis(
        analysis_id="A1",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=zones,
        liquidity_map=[
            LiquidityLevel(label="BSL", price=112.0, side="ABOVE", source_tf="H4", distance=12.0),
            LiquidityLevel(label="SSL", price=89.0, side="BELOW", source_tf="H4", distance=11.0),
        ],
        approved=True,
    )

    selected = apply_two_zone_institutional_map(analysis, _snapshot())

    assert len(selected) == 2
    assert [z.zone_id for z in selected] == ["H4_SELL", "H4_BUY"]
    assert all("PRIMARY_INSTITUTIONAL_ZONE" in z.notes for z in selected)
    assert "Two-zone institutional map only" in analysis.trader_brief


def test_liquidity_support_does_not_stretch_envelope(monkeypatch):
    import app.institutional_two_zone as policy

    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 0)
    monkeypatch.setattr(policy, "_candidate_map", lambda s: {})

    sell = _zone("H4_SELL", Direction.SELL, "H4", 110.0, 110.2, Grade.A)
    analysis = Analysis(
        analysis_id="A2",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[sell],
        liquidity_map=[
            LiquidityLevel(label="DISTAL_BSL", price=124.0, side="ABOVE", source_tf="H4", distance=24.0)
        ],
        approved=True,
    )

    apply_two_zone_institutional_map(analysis, _snapshot())

    # H4 envelope uses 0.60 M15 ATR either side of core midpoint: compact and
    # independent of the distant liquidity price.
    assert analysis.zones[0].zone_low == 108.9
    assert analysis.zones[0].zone_high == 111.3
    assert analysis.zones[0].zone_high < 124.0
    assert "LIQUIDITY_REFERENCE_ONLY_DOES_NOT_STRETCH_ZONE" in analysis.zones[0].notes


def test_primary_zone_interaction_uses_core_not_outer_envelope(monkeypatch):
    import app.institutional_two_zone as policy

    monkeypatch.setattr(policy, "atr", lambda bars: 2.0)
    zone = _zone("Z1", Direction.SELL, "H4", 100.0, 101.0, Grade.A)
    zone.core_method = "ACTIONABLE|H4_PARENT_UNREFINED"
    zone.zone_low = 95.0
    zone.zone_high = 106.0

    assert primary_zone_interacting(zone, _snapshot(mid=101.4)) is True
    assert primary_zone_interacting(zone, _snapshot(mid=103.0)) is False
