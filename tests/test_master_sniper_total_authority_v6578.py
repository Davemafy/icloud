from types import SimpleNamespace

from app.models import Direction
from app import institutional_two_zone as zoning
from app import zone_runtime_policy as policy


def _candidate(direction=Direction.SELL):
    return SimpleNamespace(
        direction=direction,
        core_low=4279.0,
        core_high=4283.0,
        zone_low=4275.0,
        zone_high=4290.0,
    )


def _snapshot():
    return SimpleNamespace(mid=4266.0)


def test_master_sniper_source_geometry_is_not_rejected_by_external_liquidity():
    policy.install_zone_geometry_policy()
    candidate = _candidate(Direction.SELL)
    external_bsl = SimpleNamespace(label="H4_BSL", source_tf="H4", price=4300.0, distance=34.0)

    core_low, core_high = zoning._normalize_core(candidate, _snapshot())
    attached = zoning._select_liquidity(candidate, core_low, core_high, [external_bsl], _snapshot())
    geometry = zoning._build_geometry(candidate, core_low, core_high, attached, _snapshot())

    assert attached is external_bsl
    assert geometry[:2] == (4275.0, 4290.0)


def test_master_sniper_market_side_is_ranking_not_zone_existence():
    assert policy._market_side_rejection(Direction.SELL, 4275.0, 4290.0, 4305.0) == ("", "")
    assert policy._market_side_rejection(Direction.BUY, 4229.0, 4240.0, 4210.0) == ("", "")


def test_bplus_remains_in_executable_zoning_tier():
    zone = SimpleNamespace(
        grade=zoning.Grade.B_PLUS,
        touch_count=0,
        source_tf="H1",
        location_score=5.0,
        source_ts=1,
        zone_low=4229.0,
        zone_high=4240.0,
    )
    snapshot = SimpleNamespace(mid=4266.0, atr_h1=20.0, xau_h1=[])
    assert policy.intraday_zone_rank(zone, snapshot)[0] == 0
