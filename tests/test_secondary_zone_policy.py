from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.secondary_zone_policy import apply_secondary_zone_policy


def _zone(zone_id: str, direction: Direction, low: float, high: float, core_low: float, core_high: float, source_ts: int, touches: int = 0) -> Zone:
    required = "BSL_IN_MARKED_ZONE" if direction == Direction.SELL else "SSL_IN_MARKED_ZONE"
    liquidity_note = (
        f"attached_liquidity:BSL:H1_BSL@{core_high:.5f}"
        if direction == Direction.SELL
        else f"attached_liquidity:SSL:H1_SSL@{core_low:.5f}"
    )
    return Zone(
        zone_id=zone_id,
        original_direction=direction,
        flip_direction=direction.opposite(),
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=core_low,
        core_high=core_high,
        core_method="ARMED|PROMPT_SWEEP_ROOM_GEOMETRY",
        location_score=9.0,
        zone_low=low,
        zone_high=high,
        touch_count=touches,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", required],
        independent_confluence_count=2,
        source_ts=source_ts,
        invalidation_level=high if direction == Direction.SELL else low,
        invalidation_rule="M15 accepted invalidation",
        clear_run=1.0,
        notes=[liquidity_note, "sweep_room_points:500.0"],
    )


def _snapshot(mid: float = 4295.0) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=1,
        bid=mid - 0.1,
        ask=mid + 0.1,
        spread_points=20,
        point=0.01,
        atr_h1=20.0,
        atr_m15=6.0,
    )


def test_sell_level_two_is_distinct_higher_reserve_and_never_execution(monkeypatch):
    from app import institutional_two_zone as zoning

    primary = _zone("SELL_L1", Direction.SELL, 4282.75, 4322.75, 4305.88, 4315.88, 100, touches=1)
    overlapping = _zone("SELL_OVERLAP", Direction.SELL, 4310.0, 4350.0, 4330.0, 4340.0, 200)
    higher = _zone("SELL_L2", Direction.SELL, 4367.49, 4407.49, 4392.49, 4402.49, 300)
    candidates = ["primary", "overlap", "higher"]
    zones = {"primary": primary, "overlap": overlapping, "higher": higher}

    monkeypatch.setattr(zoning, "_build_candidates", lambda snapshot: candidates)
    monkeypatch.setattr(zoning, "_candidate_zone", lambda candidate, snapshot, liq, context, index: (zones[candidate], {}))
    monkeypatch.setattr(zoning, "_rank", lambda zone, snapshot: (abs(zone.zone_low - snapshot.mid),))

    analysis = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        overall_bias=Direction.SELL,
        zones=[primary],
        selected_zone_id="SELL_L1",
    )
    apply_secondary_zone_policy(analysis, _snapshot())

    reserve = analysis.execution_policy["public_zone_map"]["secondary"]["sell"]
    assert reserve["low"] == 4367.49
    assert reserve["high"] == 4407.49
    assert reserve["state"] == "RESERVE"
    assert reserve["execution_authority"] is False
    assert reserve["fresh_requalification_required"] is True
    assert analysis.selected_zone_id == "SELL_L1"
    assert [z.zone_id for z in analysis.zones] == ["SELL_L1"]


def test_buy_level_two_must_be_lower_than_primary_and_is_not_forced(monkeypatch):
    from app import institutional_two_zone as zoning

    primary = _zone("BUY_L1", Direction.BUY, 4248.57, 4288.57, 4253.57, 4270.98, 100, touches=1)
    overlapping = _zone("BUY_OVERLAP", Direction.BUY, 4220.0, 4260.0, 4230.0, 4240.0, 200)

    monkeypatch.setattr(zoning, "_build_candidates", lambda snapshot: ["primary", "overlap"])
    monkeypatch.setattr(
        zoning,
        "_candidate_zone",
        lambda candidate, snapshot, liq, context, index: ((primary if candidate == "primary" else overlapping), {}),
    )
    monkeypatch.setattr(zoning, "_rank", lambda zone, snapshot: (0,))

    analysis = Analysis(
        analysis_id="A2",
        generated_at=1,
        snapshot_at=1,
        overall_bias=Direction.SELL,
        zones=[primary],
        selected_zone_id="BUY_L1",
    )
    apply_secondary_zone_policy(analysis, _snapshot())

    reserve = analysis.execution_policy["public_zone_map"]["secondary"]["buy"]
    assert reserve is None
    assert analysis.selected_zone_id == "BUY_L1"
    assert [z.zone_id for z in analysis.zones] == ["BUY_L1"]
