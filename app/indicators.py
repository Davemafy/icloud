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
