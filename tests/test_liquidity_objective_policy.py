from __future__ import annotations

from app.liquidity_objective_policy import apply_liquidity_objective_policy
from app.models import Analysis, Direction, Grade, LiquidityLevel, MarketSnapshot, Zone


def _zone(zone_id: str, direction: Direction, core_low: float, core_high: float, zone_low: float, zone_high: float) -> Zone:
    return Zone(
        zone_id=zone_id,
        original_direction=direction,
        flip_direction=direction.opposite(),
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        core_low=core_low,
        core_high=core_high,
        core_method="ARMED|PROMPT_SWEEP_ROOM_GEOMETRY",
        location_score=8.0,
        zone_low=zone_low,
        zone_high=zone_high,
        invalidation_level=zone_high if direction == Direction.SELL else zone_low,
        invalidation_rule="M15 accepted invalidation",
    )


def test_sell_targets_follow_liquidity_and_stop_in_front_of_buy_zone() -> None:
    sell = _zone("SELL1", Direction.SELL, 4305.88, 4315.88, 4282.75, 4322.75)
    buy = _zone("BUY1", Direction.BUY, 4253.57, 4270.98, 4248.57, 4288.57)
    analysis = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id="SELL1",
        liquidity_map=[
            LiquidityLevel(label="H1_SSL", price=4300.54, side="BELOW", source_tf="H1", distance=1.0),
            LiquidityLevel(label="H4_SSL", price=4292.10, side="BELOW", source_tf="H4", distance=2.0),
            LiquidityLevel(label="H1_SSL", price=4286.00, side="BELOW", source_tf="H1", distance=3.0),
            LiquidityLevel(label="H1_SSL", price=4253.57, side="BELOW", source_tf="H1", distance=4.0),
        ],
    )
    snapshot = MarketSnapshot(
        sent_at=1789430400,
        bid=4290.00,
        ask=4290.18,
        spread_points=18,
        point=0.01,
        atr_m15=1.50,
        atr_h1=20.0,
    )

    apply_liquidity_objective_policy(analysis, snapshot)

    assert sell.original_target1 == 4300.54
    assert sell.original_target2 == 4292.10
    # Active BUY envelope begins at 4288.57 high/proximal edge for a falling SELL move.
    # Target must front-run that zone instead of shooting through toward 4253.57 SSL.
    assert sell.original_target3 > 4288.57
    assert sell.original_target3 < 4292.10
    assert sell.original_runner == 0.0
    assert sell.original_target3 != 4253.57


def test_target_map_does_not_remove_valid_zone() -> None:
    sell = _zone("SELL1", Direction.SELL, 4305.88, 4315.88, 4282.75, 4322.75)
    analysis = Analysis(
        analysis_id="A2",
        generated_at=1,
        snapshot_at=1,
        overall_bias=Direction.SELL,
        zones=[sell],
        selected_zone_id="SELL1",
        liquidity_map=[],
    )
    snapshot = MarketSnapshot(
        sent_at=1789430400,
        bid=4290.00,
        ask=4290.18,
        spread_points=18,
        point=0.01,
        atr_m15=1.50,
        atr_h1=20.0,
    )

    apply_liquidity_objective_policy(analysis, snapshot)

    assert analysis.zones[0].zone_id == "SELL1"
    assert analysis.zones[0].grade == Grade.A_PLUS
    assert analysis.zones[0].original_target1 == 0.0
    assert analysis.execution_policy["liquidity_objectives"]["zone_validity_independent_of_targets"] is True
