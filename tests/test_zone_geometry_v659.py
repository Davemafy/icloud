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


def test_master_sniper_core_normalization_preserves_native_source_core():
    policy.install_zone_geometry_policy()
    s = _snapshot()

    h1 = _candidate("H1", Direction.SELL, 4305.0, 4306.0, 4304.0, 4307.0)
    assert zoning._normalize_core(h1, s) == (4305.0, 4306.0)

    h4 = _candidate("H4", Direction.SELL, 4305.0, 4306.0, 4304.0, 4307.0)
    assert zoning._normalize_core(h4, s) == (4305.0, 4306.0)

    refined = _candidate("H4>H1", Direction.BUY, 4299.0, 4300.0, 4298.0, 4302.0)
    assert zoning._normalize_core(refined, s) == (4299.0, 4300.0)


def test_master_sniper_sell_rejects_remote_bsl_outside_source_envelope():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    candidate = _candidate("H1", Direction.SELL, 4305.0, 4306.0, 4304.0, 4307.0)
    core_low, core_high = zoning._normalize_core(candidate, s)
    remote = _liq("H1_BSL", "H1", 4310.0)

    assert zoning._select_liquidity(candidate, core_low, core_high, [remote], s) is None


def test_master_sniper_sell_uses_bsl_already_inside_source_without_expansion():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    candidate = _candidate("H1", Direction.SELL, 4305.0, 4306.0, 4304.0, 4307.0)
    core_low, core_high = zoning._normalize_core(candidate, s)
    level = _liq("H1_BSL", "H1", 4306.5)

    attached = zoning._select_liquidity(candidate, core_low, core_high, [level], s)
    assert attached is level
    low, high, actual_room = zoning._build_geometry(candidate, core_low, core_high, attached, s)
    assert (low, high) == (4304.0, 4307.0)
    assert actual_room == 0.5


def test_master_sniper_buy_rejects_remote_ssl_outside_source_envelope():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    candidate = _candidate("H4", Direction.BUY, 4294.0, 4295.0, 4293.0, 4296.0)
    core_low, core_high = zoning._normalize_core(candidate, s)
    remote = _liq("H4_SSL", "H4", 4289.0)

    assert zoning._select_liquidity(candidate, core_low, core_high, [remote], s) is None


def test_master_sniper_buy_uses_ssl_already_inside_source_without_expansion():
    policy.install_zone_geometry_policy()
    s = _snapshot()
    candidate = _candidate("H4", Direction.BUY, 4294.0, 4295.0, 4293.0, 4296.0)
    core_low, core_high = zoning._normalize_core(candidate, s)
    level = _liq("H4_SSL", "H4", 4293.5)

    attached = zoning._select_liquidity(candidate, core_low, core_high, [level], s)
    assert attached is level
    low, high, actual_room = zoning._build_geometry(candidate, core_low, core_high, attached, s)
    assert (low, high) == (4293.0, 4296.0)
    assert actual_room == 0.5
