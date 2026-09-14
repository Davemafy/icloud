from app.institutional_two_zone import (
    CORE_MAX_POINTS,
    CORE_MIN_POINTS,
    ENVELOPE_MAX_POINTS,
    ENVELOPE_MIN_POINTS,
    MIN_SWEEP_ROOM_POINTS,
    PromptCandidate,
    _build_geometry,
    _normalize_core,
    _select_liquidity,
)
from app.models import Direction, LiquidityLevel, MarketSnapshot


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=1,
        bid=100.0,
        ask=100.16,
        spread_points=16,
        point=0.01,
    )


def test_sell_geometry_reserves_sweep_room_inside_envelope():
    s = _snapshot()
    c = PromptCandidate(
        direction=Direction.SELL,
        source_tf="H4",
        source_ts=1,
        core_low=100.0,
        core_high=100.2,
        zone_low=99.0,
        zone_high=101.0,
        strength=2.0,
        fvg=True,
        source_kind="DISPLACEMENT_BOS_SOURCE",
        volume_expansion=False,
        method="PROMPT_H4_SOURCE_CANDLE",
    )
    core_low, core_high = _normalize_core(c, s)
    assert CORE_MIN_POINTS <= (core_high - core_low) / s.point <= CORE_MAX_POINTS

    level = LiquidityLevel(label="H4_BSL", price=100.5, side="ABOVE", source_tf="H4", distance=0.5)
    geometry = _build_geometry(c, core_low, core_high, level, s)
    assert geometry is not None
    low, high, sweep_room = geometry
    assert ENVELOPE_MIN_POINTS <= (high - low) / s.point <= ENVELOPE_MAX_POINTS
    assert sweep_room / s.point >= MIN_SWEEP_ROOM_POINTS
    assert low <= level.price <= high


def test_buy_geometry_reserves_sweep_room_inside_envelope():
    s = _snapshot()
    c = PromptCandidate(
        direction=Direction.BUY,
        source_tf="H4",
        source_ts=1,
        core_low=100.0,
        core_high=100.2,
        zone_low=99.0,
        zone_high=101.0,
        strength=2.0,
        fvg=False,
        source_kind="LIQUIDITY_SWEEP_REJECTION",
        volume_expansion=False,
        method="PROMPT_H4_SOURCE_CANDLE",
    )
    core_low, core_high = _normalize_core(c, s)
    level = LiquidityLevel(label="H4_SSL", price=99.5, side="BELOW", source_tf="H4", distance=0.5)
    geometry = _build_geometry(c, core_low, core_high, level, s)
    assert geometry is not None
    low, high, sweep_room = geometry
    assert ENVELOPE_MIN_POINTS <= (high - low) / s.point <= ENVELOPE_MAX_POINTS
    assert sweep_room / s.point >= MIN_SWEEP_ROOM_POINTS
    assert low <= level.price <= high


def test_liquidity_too_far_for_300_point_contract_is_not_selected():
    s = _snapshot()
    c = PromptCandidate(
        direction=Direction.SELL,
        source_tf="H4",
        source_ts=1,
        core_low=100.0,
        core_high=100.2,
        zone_low=99.0,
        zone_high=101.0,
        strength=2.0,
        fvg=False,
        source_kind="DISPLACEMENT_BOS_SOURCE",
        volume_expansion=False,
        method="PROMPT_H4_SOURCE_CANDLE",
    )
    core_low, core_high = _normalize_core(c, s)
    levels = [
        LiquidityLevel(label="D1_BSL", price=103.0, side="ABOVE", source_tf="D1", distance=3.0)
    ]
    assert _select_liquidity(c, core_low, core_high, levels, s) is None
