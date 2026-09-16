from app import dynamic_continuation_zoning as policy
from app.models import Analysis, Direction, Grade, LiquidityLevel, MarketSnapshot, Zone, ZoneState


def _snapshot(mid: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=20_000,
        bid=mid - 0.1,
        ask=mid + 0.1,
        spread_points=20.0,
        point=0.01,
        atr_h1=10.0,
        atr_m15=2.0,
    )


def _zone(
    zone_id: str,
    direction: Direction,
    grade: Grade,
    touches: int,
    core_low: float,
    core_high: float,
    zone_low: float,
    zone_high: float,
) -> Zone:
    return Zone(
        zone_id=zone_id,
        original_direction=direction,
        flip_direction=direction.opposite(),
        setup_type="CONTINUATION" if direction == Direction.SELL else "REVERSAL",
        source_tf="H1",
        grade=grade,
        state=ZoneState.ACTIVE,
        core_low=core_low,
        core_high=core_high,
        core_method="ARMED|TEST",
        location_score=8.0,
        zone_low=zone_low,
        zone_high=zone_high,
        touch_count=touches,
        confluences=["LIQUIDITY_IN_MARKED_ZONE"],
        independent_confluence_count=1,
        source_ts=19_000,
        invalidation_level=zone_high if direction == Direction.SELL else zone_low,
        invalidation_rule="test",
        original_target1=80.0 if direction == Direction.SELL else 120.0,
    )


def _analysis(zones: list[Zone]) -> Analysis:
    return Analysis(
        analysis_id="A_TEST",
        generated_at=20_000,
        snapshot_at=20_000,
        overall_bias=Direction.SELL,
        zones=zones,
        selected_zone_id=zones[0].zone_id if zones else "",
        liquidity_map=[],
        execution_policy={"public_zone_map": {}},
    )


def _event() -> policy.ContinuationEvent:
    return policy.ContinuationEvent(
        direction=Direction.SELL,
        source_tf="H1",
        source_ts=19_100,
        displacement_ts=19_200,
        strength=2.2,
        fvg_low=104.0,
        fvg_high=105.0,
        age_bars=1,
    )


def test_exhausted_countertrend_buy_is_demoted_from_execution_map(monkeypatch):
    sell = _zone("SELL_REMOTE", Direction.SELL, Grade.A_PLUS, 0, 130.0, 131.0, 128.0, 132.0)
    buy = _zone("BUY_USED", Direction.BUY, Grade.B_PLUS, 3, 99.0, 101.0, 97.0, 103.0)
    analysis = _analysis([sell, buy])
    analysis.selected_zone_id = "SELL_REMOTE"

    monkeypatch.setattr(policy, "active_owner_snapshot", lambda now: None)
    monkeypatch.setattr(policy, "_recent_events", lambda snapshot, direction: [_event()])
    monkeypatch.setattr(
        policy,
        "_expansion_state",
        lambda snapshot, context, events: {"aligned": True, "d1": "SELL", "h1": "SELL", "h4": "SELL", "recent_event_count": 1},
    )
    monkeypatch.setattr(policy, "_build_dynamic_zone", lambda event, analysis, snapshot: None)

    policy.apply_dynamic_continuation_rezone(analysis, _snapshot())

    assert [z.zone_id for z in analysis.zones] == ["SELL_REMOTE"]
    meta = analysis.execution_policy["dynamic_continuation_rezone"]
    assert meta["demoted_context_zones"][0]["zone_id"] == "BUY_USED"
    assert meta["demoted_context_zones"][0]["execution_authority"] is False


def test_nearer_fresh_continuation_replaces_remote_primary(monkeypatch):
    remote = _zone("SELL_REMOTE", Direction.SELL, Grade.A_PLUS, 0, 130.0, 131.0, 128.0, 132.0)
    fresh_buy = _zone("BUY_FRESH", Direction.BUY, Grade.A_PLUS, 0, 90.0, 91.0, 88.0, 93.0)
    analysis = _analysis([remote, fresh_buy])
    dynamic = _zone("DC_H1_SELL_19200", Direction.SELL, Grade.A, 0, 104.0, 105.0, 103.0, 106.0)
    dynamic.core_method = "ARMED|DYNAMIC_CONTINUATION_REZONE|FVG_BOS_LIQUIDITY_CENTERED"
    dynamic.confluences = ["DYNAMIC_CONTINUATION_REZONE", "LIQUIDITY_CENTERED_CORE"]

    monkeypatch.setattr(policy, "active_owner_snapshot", lambda now: None)
    monkeypatch.setattr(policy, "_recent_events", lambda snapshot, direction: [_event()])
    monkeypatch.setattr(
        policy,
        "_expansion_state",
        lambda snapshot, context, events: {"aligned": True, "d1": "SELL", "h1": "SELL", "h4": "SELL", "recent_event_count": 1},
    )
    monkeypatch.setattr(policy, "_build_dynamic_zone", lambda event, analysis, snapshot: dynamic)

    policy.apply_dynamic_continuation_rezone(analysis, _snapshot(mid=100.0))

    ids = [z.zone_id for z in analysis.zones]
    assert "SELL_REMOTE" not in ids
    assert "DC_H1_SELL_19200" in ids
    assert "BUY_FRESH" in ids
    assert analysis.selected_zone_id == "DC_H1_SELL_19200"
    meta = analysis.execution_policy["dynamic_continuation_rezone"]
    assert meta["replaced_primary"]["zone_id"] == "SELL_REMOTE"
    assert meta["dynamic_primary"]["zone_id"] == "DC_H1_SELL_19200"


def test_acquired_thesis_protects_map_from_rezoning(monkeypatch):
    sell = _zone("SELL_REMOTE", Direction.SELL, Grade.A_PLUS, 0, 130.0, 131.0, 128.0, 132.0)
    buy = _zone("BUY_USED", Direction.BUY, Grade.B_PLUS, 3, 99.0, 101.0, 97.0, 103.0)
    analysis = _analysis([sell, buy])

    monkeypatch.setattr(policy, "active_owner_snapshot", lambda now: {"reaction_key": "BUY|H1|1", "ownership_acquired_at": 1})
    monkeypatch.setattr(policy, "_recent_events", lambda snapshot, direction: [_event()])
    monkeypatch.setattr(
        policy,
        "_expansion_state",
        lambda snapshot, context, events: {"aligned": True, "d1": "SELL", "h1": "SELL", "h4": "SELL", "recent_event_count": 1},
    )

    policy.apply_dynamic_continuation_rezone(analysis, _snapshot())

    assert [z.zone_id for z in analysis.zones] == ["SELL_REMOTE", "BUY_USED"]
    assert analysis.execution_policy["dynamic_continuation_rezone"]["owner_protected"] is True


def test_liquidity_centered_geometry_has_buffer_on_both_sides():
    snap = _snapshot()
    event = _event()
    geometry = policy._liquidity_centered_geometry(event, liquidity_price=104.5, snapshot=snap)
    assert geometry is not None
    core_low, core_high, zone_low, zone_high = geometry
    assert core_low < 104.5 < core_high
    assert round(104.5 - core_low, 8) == round(core_high - 104.5, 8)
    assert (104.5 - zone_low) / snap.point >= policy.MIN_SWEEP_ROOM_POINTS
    assert (zone_high - 104.5) / snap.point >= policy.MIN_SWEEP_ROOM_POINTS


def test_fvg_cannot_create_dynamic_zone_without_structural_liquidity(monkeypatch):
    analysis = _analysis([])
    analysis.liquidity_map = [
        LiquidityLevel(label="PSY", price=104.5, side="ABOVE", source_tf="PSY", distance=4.5)
    ]
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 0)

    zone = policy._build_dynamic_zone(_event(), analysis, _snapshot())

    assert zone is None
