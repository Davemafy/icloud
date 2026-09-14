from __future__ import annotations

import statistics

from .engine import Origin, _overlap, atr, displacement_origins
from .models import Bar, Direction


SWEEP_LOOKBACK = 8
FOLLOW_THROUGH_BARS = 3
MIN_REJECTION_WICK_FRACTION = 0.30
MIN_FOLLOW_THROUGH_ATR = 0.60
EQUAL_LIQUIDITY_TOLERANCE_ATR = 0.12


def _rng(bar: Bar) -> float:
    return max(0.0, float(bar.high) - float(bar.low))


def _median_range(bars: list[Bar], n: int = 20) -> float:
    values = [_rng(x) for x in bars[-n:] if _rng(x) > 0]
    return statistics.median(values) if values else 0.0


def _rejection_zone(bar: Bar, direction: Direction) -> tuple[float, float]:
    """Compact rejection source: wick extreme back to the body edge."""
    body_low, body_high = sorted((float(bar.open), float(bar.close)))
    if direction == Direction.SELL:
        low, high = body_high, float(bar.high)
    else:
        low, high = float(bar.low), body_low
    if high <= low:
        low, high = sorted((float(bar.open), float(bar.close)))
    if high <= low:
        low, high = float(bar.low), float(bar.high)
    return low, high


def liquidity_sweep_rejection_origins(
    bars: list[Bar],
    tf: str,
    max_items: int = 12,
) -> list[Origin]:
    """Find closed-candle liquidity raids/equal-high-low rejections with follow-through."""
    if len(bars) < 30:
        return []
    med = _median_range(bars, 20)
    a = atr(bars)
    noise = max(med, a, 1e-9)
    tolerance = EQUAL_LIQUIDITY_TOLERANCE_ATR * noise
    out: list[Origin] = []
    start = max(SWEEP_LOOKBACK, len(bars) - 180)

    for i in range(start, len(bars) - 1):
        bar = bars[i]
        r = _rng(bar)
        if r <= 0:
            continue
        prior = bars[max(0, i - SWEEP_LOOKBACK):i]
        if len(prior) < 3:
            continue
        prior_high = max(float(x.high) for x in prior)
        prior_low = min(float(x.low) for x in prior)
        body_low, body_high = sorted((float(bar.open), float(bar.close)))
        upper_wick = max(0.0, float(bar.high) - body_high)
        lower_wick = max(0.0, body_low - float(bar.low))
        follow = bars[i + 1:min(len(bars), i + 1 + FOLLOW_THROUGH_BARS)]
        if not follow:
            continue

        # Equal-high liquidity is accepted as a raid when the wick reaches the
        # prior pool within a small ATR tolerance and then closes back below it.
        sell_raid = float(bar.high) >= prior_high - tolerance and float(bar.close) < prior_high
        sell_reject = upper_wick / r >= MIN_REJECTION_WICK_FRACTION or float(bar.close) < float(bar.open)
        sell_move = min(float(x.low) for x in follow) <= float(bar.close) - MIN_FOLLOW_THROUGH_ATR * noise
        if sell_raid and sell_reject and sell_move:
            lo, hi = _rejection_zone(bar, Direction.SELL)
            strength = max(1.0, (float(bar.high) - min(float(x.low) for x in follow)) / noise)
            out.append(Origin(Direction.SELL, lo, hi, int(bar.ts), tf, i, round(strength, 3), False))

        # Same logic for equal-low / sell-side liquidity raids.
        buy_raid = float(bar.low) <= prior_low + tolerance and float(bar.close) > prior_low
        buy_reject = lower_wick / r >= MIN_REJECTION_WICK_FRACTION or float(bar.close) > float(bar.open)
        buy_move = max(float(x.high) for x in follow) >= float(bar.close) + MIN_FOLLOW_THROUGH_ATR * noise
        if buy_raid and buy_reject and buy_move:
            lo, hi = _rejection_zone(bar, Direction.BUY)
            strength = max(1.0, (max(float(x.high) for x in follow) - float(bar.low)) / noise)
            out.append(Origin(Direction.BUY, lo, hi, int(bar.ts), tf, i, round(strength, 3), False))

    deduped: list[Origin] = []
    for origin in reversed(out):
        if any(
            origin.direction == existing.direction
            and _overlap(origin.low, origin.high, existing.low, existing.high, 0.0)
            for existing in deduped
        ):
            continue
        deduped.append(origin)
        if len(deduped) >= max_items:
            break
    return list(reversed(deduped))


def prompt_origins(bars: list[Bar], tf: str, max_items: int = 18) -> list[Origin]:
    """Union displacement sources with liquidity-rejection sources."""
    raw = [
        *displacement_origins(bars, tf, max_items=max_items),
        *liquidity_sweep_rejection_origins(bars, tf, max_items=max_items),
    ]
    raw.sort(key=lambda x: (int(x.source_ts), float(x.strength)))
    deduped: list[Origin] = []
    for origin in reversed(raw):
        if any(
            origin.direction == existing.direction
            and _overlap(origin.low, origin.high, existing.low, existing.high, 0.0)
            for existing in deduped
        ):
            continue
        deduped.append(origin)
        if len(deduped) >= max_items:
            break
    return list(reversed(deduped))
