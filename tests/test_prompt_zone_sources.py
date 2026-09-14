from app.models import Bar, Direction
from app.prompt_zone_sources import liquidity_sweep_rejection_origins


def _bar(ts, o, h, l, c):
    return Bar(ts=ts, open=o, high=h, low=l, close=c, volume=1.0)


def test_upper_raid_rejection_source_detected():
    bars = [_bar(i, 100.0, 101.0, 99.0, 100.2) for i in range(30)]
    bars.extend([
        _bar(30, 100.4, 102.0, 99.8, 100.5),
        _bar(31, 100.4, 100.6, 97.8, 98.2),
        _bar(32, 98.2, 98.5, 97.0, 97.4),
        _bar(33, 97.4, 97.8, 96.8, 97.0),
    ])
    origins = liquidity_sweep_rejection_origins(bars, "H4")
    found = [x for x in origins if x.direction == Direction.SELL]
    assert found
    assert found[-1].low <= 102.0 <= found[-1].high


def test_lower_raid_rejection_source_detected():
    bars = [_bar(i, 100.0, 101.0, 99.0, 99.8) for i in range(30)]
    bars.extend([
        _bar(30, 99.6, 100.2, 98.0, 99.5),
        _bar(31, 99.6, 102.2, 99.4, 101.8),
        _bar(32, 101.8, 103.0, 101.4, 102.6),
        _bar(33, 102.6, 103.2, 102.2, 103.0),
    ])
    origins = liquidity_sweep_rejection_origins(bars, "H4")
    found = [x for x in origins if x.direction == Direction.BUY]
    assert found
    assert found[-1].low <= 98.0 <= found[-1].high
