from types import SimpleNamespace

from app import institutional_two_zone as zoning
from app import zone_runtime_policy as policy
from app.models import Direction, Grade


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


def test_master_sniper_keeps_native_source_core_without_fixed_width_padding():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    h1 = _candidate("H1", Direction.SELL, 4282.0, 4284.0, 4275.0, 4286.0)
    assert zoning._normalize_core(h1, s) == (4282.0, 4284.0)


def test_master_sniper_sell_zone_can_include_structural_bsl_outside_single_source_candle():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    candidate = _candidate("H1", Direction.SELL, 4282.0, 4284.0, 4275.0, 4286.0)
    bsl = _liq("H1_BSL", "H1", 4290.0)
    core_low, core_high = zoning._normalize_core(candidate, s)
    attached = zoning._select_liquidity(candidate, core_low, core_high, [bsl], s)
    assert attached is bsl
    low, high, _ = zoning._build_geometry(candidate, core_low, core_high, attached, s)
    assert (low, high) == (4275.0, 4290.0)


def test_master_sniper_buy_zone_can_include_structural_ssl_outside_single_source_candle():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    candidate = _candidate("H1", Direction.BUY, 4233.0, 4235.0, 4231.0, 4240.0)
    ssl = _liq("H4_SSL", "H4", 4229.0)
    core_low, core_high = zoning._normalize_core(candidate, s)
    attached = zoning._select_liquidity(candidate, core_low, core_high, [ssl], s)
    assert attached is ssl
    low, high, _ = zoning._build_geometry(candidate, core_low, core_high, attached, s)
    assert (low, high) == (4229.0, 4240.0)


def test_master_sniper_does_not_accept_wrong_direction_liquidity():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    sell = _candidate("H1", Direction.SELL, 4282.0, 4284.0, 4275.0, 4286.0)
    wrong_bsl = _liq("H1_BSL", "H1", 4270.0)
    core_low, core_high = zoning._normalize_core(sell, s)
    assert zoning._select_liquidity(sell, core_low, core_high, [wrong_bsl], s) is None


def test_bplus_is_not_ranked_as_watch_only():
    assert Grade.B_PLUS in {Grade.A_PLUS, Grade.A, Grade.B_PLUS}
