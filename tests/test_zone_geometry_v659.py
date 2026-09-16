from types import SimpleNamespace

from app import institutional_two_zone as zoning
from app import zone_runtime_policy as policy
from app.models import Direction


def _snapshot(point: float = 0.01):
    return SimpleNamespace(point=point)


def _candidate(source_tf: str, direction: Direction, core_low: float, core_high: float, zone_low: float, zone_high: float):
    return SimpleNamespace(
        source_tf=source_tf,
        direction=direction,
        core_low=core_low,
        core_high=core_high,
        zone_low=zone_low,
        zone_high=zone_high,
    )


def _liq(label: str, source_tf: str, price: float, distance: float = 1.0):
    return SimpleNamespace(label=label, source_tf=source_tf, price=price, distance=distance)


def test_v659_core_normalization_is_source_timeframe_specific():
    policy.install_zone_geometry_policy()
    s = _snapshot()

    h1 = _candidate("H1", Direction.SELL, 4305.0, 4306.0, 4304.0, 4307.0)
    assert zoning._normalize_core(h1, s) == (4300.0, 4306.0)  # 60 pips minimum

    h4 = _candidate("H4", Direction.SELL, 4305.0, 4306.0, 4304.0, 4307.0)
    assert zoning._normalize_core(h4, s) == (4298.0, 4306.0)  # 80 pips minimum

    refined = _candidate("H4>H1", Direction.BUY, 4299.0, 4300.0, 4298.0, 4302.0)
    assert zoning._normalize_core(refined, s) == (4299.0, 4305.0)  # H1-refined 60-pip core


def test_v659_sell_geometry_keeps_bsl_and_50_pip_sweep_inside_h1_envelope():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    candidate = _candidate("H1", Direction.SELL, 4305.0, 4306.0, 4304.0, 4307.0)
    core_low, core_high = zoning._normalize_core(candidate, s)
    level = _liq("H1_BSL", "H1", 4310.0)

    attached = zoning._select_liquidity(candidate, core_low, core_high, [level], s)
    assert attached is level

    geometry = zoning._build_geometry(candidate, core_low, core_high, attached, s)
    assert geometry is not None
    low, high, actual_room = geometry
    assert low <= core_low
    assert high >= 4315.0
    assert round((high - low) / s.point / policy.XAU_POINTS_PER_PIP, 1) >= 140.0
    assert round(actual_room / s.point / policy.XAU_POINTS_PER_PIP, 1) >= 50.0


def test_v659_rejects_sell_liquidity_that_needs_more_than_h1_max_envelope():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    candidate = _candidate("H1", Direction.SELL, 4305.0, 4306.0, 4304.0, 4307.0)
    core_low, core_high = zoning._normalize_core(candidate, s)
    too_far_bsl = _liq("H1_BSL", "H1", 4318.0)

    assert zoning._select_liquidity(candidate, core_low, core_high, [too_far_bsl], s) is None


def test_v659_buy_geometry_keeps_ssl_and_50_pip_sweep_inside_h4_envelope():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    candidate = _candidate("H4", Direction.BUY, 4294.0, 4295.0, 4293.0, 4296.0)
    core_low, core_high = zoning._normalize_core(candidate, s)
    level = _liq("H4_SSL", "H4", 4289.0)

    attached = zoning._select_liquidity(candidate, core_low, core_high, [level], s)
    assert attached is level

    geometry = zoning._build_geometry(candidate, core_low, core_high, attached, s)
    assert geometry is not None
    low, high, actual_room = geometry
    assert low <= 4284.0
    assert high >= core_high
    assert round((high - low) / s.point / policy.XAU_POINTS_PER_PIP, 1) >= 180.0
    assert round(actual_room / s.point / policy.XAU_POINTS_PER_PIP, 1) >= 50.0
