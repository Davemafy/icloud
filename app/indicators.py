from __future__ import annotations
from typing import List, Tuple, Optional
from .models import Candle, Bias


def true_range(cur: Candle, prev_close: float) -> float:
    return max(cur.high - cur.low, abs(cur.high - prev_close), abs(cur.low - prev_close))


def atr(bars: List[Candle], period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(-period, 0):
        trs.append(true_range(bars[i], bars[i-1].close))
    return sum(trs) / len(trs)


def pivots(bars: List[Candle], left: int = 2, right: int = 2) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    highs, lows = [], []
    for i in range(left, len(bars) - right):
        h = bars[i].high
        l = bars[i].low
        if all(h > bars[j].high for j in range(i-left, i)) and all(h >= bars[j].high for j in range(i+1, i+right+1)):
            highs.append((i, h))
        if all(l < bars[j].low for j in range(i-left, i)) and all(l <= bars[j].low for j in range(i+1, i+right+1)):
            lows.append((i, l))
    return highs, lows


def structural_bias(bars: List[Candle]) -> Bias:
    highs, lows = pivots(bars)
    if len(highs) < 2 or len(lows) < 2:
        return Bias.NEUTRAL
    h1, h2 = highs[-2][1], highs[-1][1]
    l1, l2 = lows[-2][1], lows[-1][1]
    if h2 < h1 and l2 < l1:
        return Bias.BEARISH
    if h2 > h1 and l2 > l1:
        return Bias.BULLISH
    return Bias.NEUTRAL


def recent_range(bars: List[Candle], lookback: int = 80) -> Tuple[float, float, float]:
    sample = bars[-lookback:]
    hi = max(x.high for x in sample)
    lo = min(x.low for x in sample)
    return hi, lo, (hi + lo) / 2.0


def equal_liquidity(bars: List[Candle], side: str, tolerance: float, lookback: int = 80) -> Optional[float]:
    highs, lows = pivots(bars[-lookback:])
    pts = [p for _, p in (highs if side == "BSL" else lows)]
    if len(pts) < 2:
        return None
    for i in range(len(pts)-1, 0, -1):
        for j in range(i-1, -1, -1):
            if abs(pts[i] - pts[j]) <= tolerance:
                return (pts[i] + pts[j]) / 2.0
    return None


def last_displacement_origin(bars: List[Candle], direction: Bias, atr_value: float, lookback: int = 40):
    if atr_value <= 0:
        return None
    for i in range(len(bars)-2, max(1, len(bars)-lookback), -1):
        c = bars[i]
        body = abs(c.close - c.open)
        rng = max(c.high - c.low, 1e-9)
        bullish = c.close > c.open
        if body >= atr_value and body / rng >= 0.65:
            if direction == Bias.BULLISH and bullish:
                prev = bars[i-1]
                return min(prev.open, prev.close), max(prev.open, prev.close)
            if direction == Bias.BEARISH and not bullish:
                prev = bars[i-1]
                return min(prev.open, prev.close), max(prev.open, prev.close)
    return None


def displacement_origins(
    bars: List[Candle],
    direction: Bias,
    atr_value: float,
    lookback: int | None = None,
    limit: int = 3,
    body_atr_multiple: float = 0.85,
):
    """Return recent displacement origins as (low, high, origin_index, displacement_index).

    This is deliberately deterministic: price levels come only from supplied OHLC.
    Multiple origins let the AI compare continuation and reversal locations without
    inventing zones. Overlapping origins are de-duplicated, newest first.
    """
    if atr_value <= 0 or len(bars) < 3:
        return []
    start = max(2, len(bars) - (lookback or len(bars)))
    out = []
    for i in range(len(bars) - 2, start - 1, -1):
        c = bars[i]
        body = abs(c.close - c.open)
        rng = max(c.high - c.low, 1e-9)
        bullish = c.close > c.open
        matches = (direction == Bias.BULLISH and bullish) or (direction == Bias.BEARISH and not bullish)
        if not matches or body < atr_value * body_atr_multiple or body / rng < 0.60:
            continue
        # Institutional source candle: prefer the nearest opposite-colour/base candle
        # immediately preceding displacement. A generic previous candle is only a
        # fallback when no opposing candle exists in the short launch base. This
        # prevents an arbitrary same-side candle from being labelled supply/demand.
        source_idx = i - 1
        scan_start = max(start - 1, i - 4)
        for j in range(i - 1, scan_start - 1, -1):
            src = bars[j]
            opposing = (direction == Bias.BULLISH and src.close <= src.open) or (
                direction == Bias.BEARISH and src.close >= src.open
            )
            if opposing:
                source_idx = j
                break
        source = bars[source_idx]

        # Use the source candle body for the executable POI so H1 refinement stays
        # practical for intraday risk. The full source high/low is preserved later
        # as evidence/invalidation context.
        low, high = min(source.open, source.close), max(source.open, source.close)
        if high - low <= 1e-12:
            low, high = source.low, source.high
        duplicate = any(not (high < x[0] or low > x[1]) for x in out)
        if duplicate:
            continue
        out.append((low, high, source_idx, i))
        if len(out) >= limit:
            break
    return out
