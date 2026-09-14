from app.institutional_two_zone import (
    _compact_envelope,
    apply_two_zone_institutional_map,
    primary_zone_interacting,
)
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


def _analysis(zones):
    return Analysis(
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
    monkeypatch.setattr(policy, "_resting_liquidity", lambda z, a, s: z.source_tf == "H4")

    selected = apply_two_zone_institutional_map(analysis, _snapshot())

    assert [z.zone_id for z in selected] == ["H4_SELL", "H4_BUY"]
    assert analysis.selected_zone_id == ""
    assert all(z.core_method.startswith("ARMED|") for z in selected)
    assert "Primary institutional map" in analysis.trader_brief
    assert analysis.execution_policy["public_zone_map"]["map_count"] == 2


def test_interacting_primary_is_marked_interacting_not_preselected(monkeypatch):
    import app.institutional_two_zone as policy

    sell = _zone("H4_SELL", Direction.SELL, "H4", 100.0, 101.0, Grade.A)
    buy = _zone("H4_BUY", Direction.BUY, "H4", 90.0, 91.0, Grade.A)
    zones = [sell, buy]
    analysis = _analysis(zones)
    monkeypatch.setattr(policy, "_build_full_candidate_pool", lambda a, s: (zones, {}))
    monkeypatch.setattr(policy, "_resting_liquidity", lambda *args, **kwargs: True)
    monkeypatch.setattr(policy, "atr", lambda bars: 2.0)
    monkeypatch.setattr(policy, "evaluate_zone_state", lambda *args, **kwargs: ZoneState.ACTIVE)

    apply_two_zone_institutional_map(analysis, _snapshot(mid=101.4))

    assert analysis.zones[0].core_method.startswith("INTERACTING|")
    assert analysis.zones[1].core_method.startswith("ARMED|")
    assert analysis.selected_zone_id == ""


def test_liquidity_support_does_not_stretch_envelope(monkeypatch):
    import app.institutional_two_zone as policy

    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)
    sell = _zone("H4_SELL", Direction.SELL, "H4", 110.0, 110.2, Grade.A)

    _compact_envelope(sell, _snapshot())

    assert sell.zone_low == 108.9
    assert sell.zone_high == 111.3
    assert "LIQUIDITY_REFERENCE_ONLY_DOES_NOT_STRETCH_ZONE" in sell.notes


def test_primary_zone_interaction_uses_core_not_outer_envelope(monkeypatch):
    import app.institutional_two_zone as policy

    monkeypatch.setattr(policy, "atr", lambda bars: 2.0)
    monkeypatch.setattr(policy, "evaluate_zone_state", lambda *args, **kwargs: ZoneState.ACTIVE)
    zone = _zone("Z1", Direction.SELL, "H4", 100.0, 101.0, Grade.A)
    zone.zone_low = 95.0
    zone.zone_high = 106.0

    assert primary_zone_interacting(zone, _snapshot(mid=101.4)) is True
    assert primary_zone_interacting(zone, _snapshot(mid=103.0)) is False
