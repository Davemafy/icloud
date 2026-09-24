from types import SimpleNamespace

from app.master_sniper_adaptive_geometry import _install_engine_geometry
from app.models import Direction, LiquidityLevel
from app import institutional_two_zone as engine


def _bars(ranges):
    return [SimpleNamespace(high=h, low=l, close=(h+l)/2, ts=i, open=(h+l)/2, tick_volume=1) for i,(l,h) in enumerate(ranges)]


def _snapshot():
    bars_h1 = _bars([(100, 110)] * 20)
    bars_h4 = _bars([(100, 120)] * 20)
    bars_m15 = _bars([(100, 104)] * 20)
    return SimpleNamespace(atr_h1=10.0, atr_m15=4.0, xau_h1=bars_h1, xau_h4=bars_h4, xau_m15=bars_m15, point=0.01)


def _candidate(direction):
    return SimpleNamespace(
        direction=direction,
        source_tf="H4>H1",
        core_low=100.0,
        core_high=102.0,
        zone_low=99.0,
        zone_high=103.0,
    )


def test_sell_attached_bsl_can_define_distal_envelope_without_fixed_width_cap():
    _install_engine_geometry()
    s = _snapshot()
    c = _candidate(Direction.SELL)
    liq = [LiquidityLevel(label="H4_BSL", price=110.0, side="HIGH", source_tf="H4", distance=7.0)]
    core = engine._normalize_core(c, s)
    level = engine._select_liquidity(c, *core, liq, s)
    assert level is not None
    low, high, room = engine._build_geometry(c, *core, level, s)
    assert low == 99.0
    assert high > 110.0
    assert room > 0.0


def test_remote_bsl_is_not_pulled_into_zone():
    _install_engine_geometry()
    s = _snapshot()
    c = _candidate(Direction.SELL)
    liq = [LiquidityLevel(label="D1_BSL", price=140.0, side="HIGH", source_tf="D1", distance=37.0)]
    core = engine._normalize_core(c, s)
    assert engine._select_liquidity(c, *core, liq, s) is None


def test_core_remains_exact_source_refinement():
    _install_engine_geometry()
    s = _snapshot()
    c = _candidate(Direction.BUY)
    assert engine._normalize_core(c, s) == (100.0, 102.0)
