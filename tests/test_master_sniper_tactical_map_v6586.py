from types import SimpleNamespace

from app.master_sniper_adaptive_geometry import _tactical_band
from app.models import Direction


def _snapshot(m15_atr=5.0, h1_atr=12.0, mid=4271.0):
    return SimpleNamespace(
        atr_m15=m15_atr,
        atr_h1=h1_atr,
        mid=mid,
        xau_m15=[],
        xau_h1=[],
        xau_h4=[],
    )


def _candidate(direction, source_low, source_high):
    return SimpleNamespace(
        direction=direction,
        source_tf="H1",
        zone_low=source_low,
        zone_high=source_high,
    )


def test_sell_map_is_tactical_band_not_full_parent_source():
    snap = _snapshot(m15_atr=5.0)
    candidate = _candidate(Direction.SELL, 4270.0, 4290.0)
    band = _tactical_band(candidate, 4282.0, 4288.0, 4285.0, snap)
    assert band is not None
    low, high = band
    assert low == 4280.0
    assert high == 4290.0
    assert (low, high) != (4270.0, 4290.0)


def test_buy_map_is_tactical_band_not_full_parent_source():
    snap = _snapshot(m15_atr=5.0)
    candidate = _candidate(Direction.BUY, 4235.0, 4265.0)
    band = _tactical_band(candidate, 4258.0, 4262.0, 4255.0, snap)
    assert band is not None
    low, high = band
    assert low == 4250.0
    assert high == 4262.0
    assert (low, high) != (4235.0, 4265.0)


def test_zone_width_scales_with_m15_volatility_not_fixed_points():
    candidate = _candidate(Direction.SELL, 4260.0, 4300.0)
    narrow = _tactical_band(candidate, 4282.0, 4288.0, 4285.0, _snapshot(m15_atr=3.0))
    wide = _tactical_band(candidate, 4282.0, 4288.0, 4285.0, _snapshot(m15_atr=8.0))
    assert narrow is not None and wide is not None
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])


def test_no_manual_master_sniper_prices_are_encoded_in_geometry():
    candidate = _candidate(Direction.SELL, 5270.0, 5290.0)
    band = _tactical_band(candidate, 5282.0, 5288.0, 5285.0, _snapshot(m15_atr=5.0))
    assert band == (5280.0, 5290.0)


def test_sep24_2026_manual_master_sniper_four_zone_regression():
    """Golden chart fixture from the 24-Sep-2026 manual Master Sniper review.

    This freezes the geometry relationship, not production prices: the prices live
    only in this regression test. 26pt spread is execution context and must never
    be used to inflate the structural alert bands.
    """
    snap = _snapshot(m15_atr=7.445, h1_atr=20.0, mid=4271.48)
    spread_points = 26
    assert spread_points == 26

    fixtures = [
        # label, direction, source, native core, attached liquidity, expected band
        ("SELL1", Direction.SELL, (4276.0, 4290.0), (4282.0, 4288.0), 4287.445, (4280.0, 4290.0)),
        ("SELL2", Direction.SELL, (4291.0, 4305.0), (4297.0, 4303.0), 4302.445, (4295.0, 4305.0)),
        ("BUY1", Direction.BUY, (4250.0, 4260.0), (4252.0, 4258.0), 4257.445, (4250.0, 4260.0)),
        ("BUY2", Direction.BUY, (4235.0, 4250.0), (4237.0, 4243.0), 4242.445, (4235.0, 4250.0)),
    ]

    bands = {}
    for label, direction, source, core, liquidity, expected in fixtures:
        candidate = _candidate(direction, *source)
        band = _tactical_band(candidate, *core, liquidity, snap)
        assert band is not None, label
        bands[label] = band
        assert band == expected, label

    assert bands["BUY2"][1] <= bands["BUY1"][0]
    assert bands["BUY1"][1] < snap.mid
    assert snap.mid < bands["SELL1"][0]
    assert bands["SELL1"][1] <= bands["SELL2"][0]
    assert bands["SELL1"] != (4252.0, 4290.0)
