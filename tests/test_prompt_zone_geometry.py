import pytest

from app.institutional_two_zone import (
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


def test_sell_geometry_preserves_native_core_and_attached_bsl_structure():
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
    assert (core_low, core_high) == (100.0, 100.2)

    level = LiquidityLevel(label="H4_BSL", price=100.5, side="ABOVE", source_tf="H4", distance=0.5)
    geometry = _build_geometry(c, core_low, core_high, level, s)
    assert geometry is not None
    low, high, sweep_room = geometry
    assert low == pytest.approx(core_low)
    assert high == pytest.approx(level.price, abs=2e-9)
    assert sweep_room == pytest.approx(0.0, abs=2e-9)
    assert c.zone_low < low and c.zone_high > high


def test_buy_geometry_preserves_native_core_and_attached_ssl_structure():
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
    assert (core_low, core_high) == (100.0, 100.2)
    level = LiquidityLevel(label="H4_SSL", price=99.5, side="BELOW", source_tf="H4", distance=0.5)
    geometry = _build_geometry(c, core_low, core_high, level, s)
    assert geometry is not None
    low, high, sweep_room = geometry
    assert low == pytest.approx(level.price, abs=2e-9)
    assert high == pytest.approx(core_high)
    assert sweep_room == pytest.approx(0.0, abs=2e-9)
    assert c.zone_low < low and c.zone_high > high


def test_liquidity_too_far_for_source_tf_professional_contract_is_not_selected():
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
        LiquidityLevel(label="D1_BSL", price=125.0, side="ABOVE", source_tf="D1", distance=25.0)
    ]
    assert _select_liquidity(c, core_low, core_high, levels, s) is None
