from types import SimpleNamespace

from app.master_sniper_adaptive_geometry import _tactical_band
from app.models import Direction


def _snapshot(m15_atr=5.0, h1_atr=12.0):
    return SimpleNamespace(
        atr_m15=m15_atr,
        atr_h1=h1_atr,
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
