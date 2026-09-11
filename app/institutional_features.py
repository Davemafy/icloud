from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .indicators import atr, pivots, structural_bias
from .models import Bias, Candle, MarketSnapshot, TimeframeBars

TF_SECONDS = {"M1": 60, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}


def closed_bars(series: TimeframeBars, now: datetime) -> list[Candle]:
    """Return only closed candles for structure/zone calculations.

    MT5 CopyRates(..., 0, ...) includes the forming candle. Institutional structure,
    BOS/CHoCH, FVG and source-zone creation must not be based on an unfinished HTF bar.
    """
    bars = list(series.bars)
    if not bars:
        return bars
    seconds = TF_SECONDS.get(series.timeframe.upper())
    if seconds is None:
        return bars
    current = now
    if current.tzinfo is None:
        current = current.replace(tzinfo=bars[-1].ts.tzinfo)
    last = bars[-1]
    if last.ts + timedelta(seconds=seconds) > current:
        return bars[:-1] if len(bars) > 1 else bars
    return bars


def fvg_list(bars: list[Candle], direction: Bias | None = None, limit: int = 8) -> list[dict[str, Any]]:
    """Deterministic 3-candle imbalances using only observed OHLC."""
    out: list[dict[str, Any]] = []
    for i in range(2, len(bars)):
        cur = bars[i]
        left = bars[i - 2]
        side = None
        lo = hi = 0.0
        if cur.low > left.high:
            side = Bias.BULLISH
            lo, hi = left.high, cur.low
        elif cur.high < left.low:
            side = Bias.BEARISH
            lo, hi = cur.high, left.low
        if side is None or (direction is not None and side != direction):
            continue
        touches = 0
        in_gap = False
        filled = False
        for b in bars[i + 1 :]:
            touched = b.low <= hi and b.high >= lo
            if touched and not in_gap:
                touches += 1
            in_gap = touched
            if b.low <= lo and b.high >= hi:
                filled = True
        out.append({
            "direction": side.value,
            "low": lo,
            "high": hi,
            "formed_at": cur.ts.isoformat(),
            "formed_index": i,
            "touches": touches,
            "filled": filled,
        })
    return out[-limit:][::-1]


def _last_prior_pivot(levels: list[tuple[int, float]], before: int) -> tuple[int, float] | None:
    for idx, value in reversed(levels):
        if idx < before:
            return idx, value
    return None


def structure_snapshot(bars: list[Candle]) -> dict[str, Any]:
    highs, lows = pivots(bars)
    bias = structural_bias(bars)
    latest_event = "NONE"
    event_level = None
    event_at = None
    event_direction = None
    # Confirm breaks on body close, not wick-only penetration.
    for i in range(max(2, len(bars) - 80), len(bars)):
        ph = _last_prior_pivot(highs, i)
        pl = _last_prior_pivot(lows, i)
        if ph and bars[i].close > ph[1]:
            prior = structural_bias(bars[:i]) if i >= 8 else Bias.NEUTRAL
            latest_event = "CHOCH" if prior == Bias.BEARISH else "BOS"
            event_direction = "BULLISH"
            event_level = ph[1]
            event_at = bars[i].ts.isoformat()
        if pl and bars[i].close < pl[1]:
            prior = structural_bias(bars[:i]) if i >= 8 else Bias.NEUTRAL
            latest_event = "CHOCH" if prior == Bias.BULLISH else "BOS"
            event_direction = "BEARISH"
            event_level = pl[1]
            event_at = bars[i].ts.isoformat()
    ih, il = pivots(bars, left=1, right=1)
    internal_bias = Bias.NEUTRAL
    if len(ih) >= 2 and len(il) >= 2:
        if ih[-1][1] > ih[-2][1] and il[-1][1] > il[-2][1]:
            internal_bias = Bias.BULLISH
        elif ih[-1][1] < ih[-2][1] and il[-1][1] < il[-2][1]:
            internal_bias = Bias.BEARISH
    return {
        "bias": bias.value,
        "external_bias": bias.value,
        "internal_bias": internal_bias.value,
        "latest_break": latest_event,
        "break_direction": event_direction,
        "break_level": event_level,
        "break_at": event_at,
        "last_swing_high": highs[-1][1] if highs else None,
        "last_swing_low": lows[-1][1] if lows else None,
        "prior_swing_high": highs[-2][1] if len(highs) >= 2 else None,
        "prior_swing_low": lows[-2][1] if len(lows) >= 2 else None,
    }


def equal_liquidity_levels(bars: list[Candle], tolerance: float, lookback: int = 160) -> dict[str, float | None]:
    sample = bars[-lookback:]
    highs, lows = pivots(sample)

    def eq(points: list[tuple[int, float]]) -> float | None:
        vals = [v for _, v in points]
        for i in range(len(vals) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                if abs(vals[i] - vals[j]) <= tolerance:
                    return (vals[i] + vals[j]) / 2.0
        return None

    return {"BSL_equal_highs": eq(highs), "SSL_equal_lows": eq(lows)}


def psychological_levels(price: float) -> dict[str, list[float]]:
    def around(step: float) -> list[float]:
        center = round(price / step) * step
        return [round(center + step * k, 4) for k in (-2, -1, 0, 1, 2)]
    return {"5": around(5.0), "10": around(10.0), "50": around(50.0), "100": around(100.0)}


def wick_rejections(bars: list[Candle], limit: int = 8) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for b in bars[-80:]:
        rng = max(b.high - b.low, 1e-12)
        body_hi = max(b.open, b.close)
        body_lo = min(b.open, b.close)
        upper = b.high - body_hi
        lower = body_lo - b.low
        if lower / rng >= 0.55 and abs(b.close - b.open) / rng <= 0.45:
            found.append({"type": "LOWER_REJECTION", "ts": b.ts.isoformat(), "low": b.low, "high": b.high})
        if upper / rng >= 0.55 and abs(b.close - b.open) / rng <= 0.45:
            found.append({"type": "UPPER_REJECTION", "ts": b.ts.isoformat(), "low": b.low, "high": b.high})
    return found[-limit:]


def volume_context(bars: list[Candle]) -> dict[str, Any]:
    """Broker tick-volume context only; never label it centralized exchange volume."""
    vals = [max(0.0, b.volume) for b in bars[-60:] if b.volume is not None]
    if len(vals) < 5:
        return {"kind": "BROKER_TICK_VOLUME", "available": False}
    baseline = median(vals[-20:-1] or vals[:-1]) or 1.0
    latest = vals[-1]
    return {
        "kind": "BROKER_TICK_VOLUME",
        "available": True,
        "latest": latest,
        "median_20": baseline,
        "latest_ratio": round(latest / baseline, 3),
    }


def trendline_liquidity(bars: list[Candle], atr_value: float) -> list[dict[str, Any]]:
    """Conservative probable trendline-liquidity references from the last 3 pivots."""
    highs, lows = pivots(bars)
    out: list[dict[str, Any]] = []
    tol = max(atr_value * 0.20, 1e-9)
    for side, pts in (("BSL_TRENDLINE", highs), ("SSL_TRENDLINE", lows)):
        if len(pts) < 3:
            continue
        p = pts[-3:]
        x1, y1 = p[0]
        x3, y3 = p[-1]
        if x3 == x1:
            continue
        slope = (y3 - y1) / (x3 - x1)
        expected_mid = y1 + slope * (p[1][0] - x1)
        if abs(p[1][1] - expected_mid) <= tol:
            projected = y1 + slope * ((len(bars) - 1) - x1)
            out.append({"type": side, "projected_level": projected, "confidence": "PROBABLE_NOT_CONFIRMED"})
    return out


def session_liquidity(m15: list[Candle], timezone_name: str, now: datetime) -> dict[str, Any]:
    tz = ZoneInfo(timezone_name)
    local_now = now.astimezone(tz)
    today = local_now.date()
    windows = {"ASIA": (0, 8), "LONDON": (8, 13), "NEW_YORK": (13, 22)}
    out: dict[str, Any] = {}
    for name, (start_h, end_h) in windows.items():
        selected = []
        for b in m15:
            local = b.ts.astimezone(tz)
            if local.date() == today and start_h <= local.hour < end_h:
                selected.append(b)
        if selected:
            out[name] = {"high": max(x.high for x in selected), "low": min(x.low for x in selected)}
    return out


def accumulation_distribution_hint(bars: list[Candle], atr_value: float) -> dict[str, Any]:
    if len(bars) < 40 or atr_value <= 0:
        return {"state": "NOT_VISIBLE_ON_CHART"}
    recent = bars[-12:]
    prior = bars[-36:-12]
    recent_range = max(b.high for b in recent) - min(b.low for b in recent)
    prior_range = max(b.high for b in prior) - min(b.low for b in prior)
    ratio = recent_range / max(prior_range, 1e-12)
    if ratio <= 0.45:
        return {"state": "COMPRESSION_ACCUMULATION_DISTRIBUTION_POSSIBLE", "confidence": "PROBABLE_NOT_CONFIRMED", "range_ratio": round(ratio, 3)}
    return {"state": "EXPANSION_OR_NORMAL", "range_ratio": round(ratio, 3)}


def origin_evidence(bars: list[Candle], origin_idx: int, disp_idx: int, direction: Bias, atr_value: float) -> dict[str, Any]:
    """Evidence that a displacement origin is institutional rather than merely a large candle."""
    if origin_idx < 0 or disp_idx <= origin_idx or disp_idx >= len(bars):
        return {"bos": False, "fvg": None, "volume_ratio": None, "source_ts": None}
    highs, lows = pivots(bars[:disp_idx])
    disp = bars[disp_idx]
    bos = False
    break_level = None
    if direction == Bias.BULLISH:
        candidates = [v for i, v in highs if i < disp_idx]
        if candidates:
            break_level = candidates[-1]
            bos = disp.close > break_level
    else:
        candidates = [v for i, v in lows if i < disp_idx]
        if candidates:
            break_level = candidates[-1]
            bos = disp.close < break_level

    fvg = None
    if disp_idx >= 2:
        left = bars[disp_idx - 2]
        if direction == Bias.BULLISH and disp.low > left.high:
            fvg = {"low": left.high, "high": disp.low}
        if direction == Bias.BEARISH and disp.high < left.low:
            fvg = {"low": disp.high, "high": left.low}

    vols = [max(0.0, x.volume) for x in bars[max(0, disp_idx - 20):disp_idx]]
    med = median(vols) if vols else 0.0
    volume_ratio = (disp.volume / med) if med > 0 else None
    origin = bars[origin_idx]
    return {
        "bos": bos,
        "break_level": break_level,
        "fvg": fvg,
        "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "source_ts": origin.ts.isoformat(),
        "source_ohlc": {"open": origin.open, "high": origin.high, "low": origin.low, "close": origin.close},
    }



def recent_liquidity_sweeps(bars: list[Candle], limit: int = 8) -> list[dict[str, Any]]:
    highs, lows = pivots(bars)
    out: list[dict[str, Any]] = []
    for i in range(max(3, len(bars) - 100), len(bars)):
        ph = _last_prior_pivot(highs, i)
        pl = _last_prior_pivot(lows, i)
        b = bars[i]
        if ph and b.high > ph[1] and b.close < ph[1]:
            out.append({"type": "BSL_SWEEP", "level": ph[1], "ts": b.ts.isoformat(), "extreme": b.high})
        if pl and b.low < pl[1] and b.close > pl[1]:
            out.append({"type": "SSL_SWEEP", "level": pl[1], "ts": b.ts.isoformat(), "extreme": b.low})
    return out[-limit:]


def probable_breaker_blocks(bars: list[Candle], limit: int = 6) -> list[dict[str, Any]]:
    """Conservative breaker candidates; labelled probable because breaker interpretation is contextual."""
    out: list[dict[str, Any]] = []
    start = max(2, len(bars) - 100)
    for k in range(start, len(bars) - 3):
        c = bars[k]
        # bearish candle later violated upward and retested -> probable bullish breaker
        if c.close < c.open:
            broken = next((j for j in range(k + 1, min(len(bars), k + 20)) if bars[j].close > c.high), None)
            if broken is not None:
                retest = next((j for j in range(broken + 1, min(len(bars), broken + 20)) if bars[j].low <= c.high and bars[j].high >= c.open), None)
                if retest is not None:
                    out.append({"direction": "BULLISH", "low": c.open, "high": c.high, "source_ts": c.ts.isoformat(), "confidence": "PROBABLE_NOT_CONFIRMED"})
        # bullish candle later violated downward and retested -> probable bearish breaker
        if c.close > c.open:
            broken = next((j for j in range(k + 1, min(len(bars), k + 20)) if bars[j].close < c.low), None)
            if broken is not None:
                retest = next((j for j in range(broken + 1, min(len(bars), broken + 20)) if bars[j].high >= c.low and bars[j].low <= c.open), None)
                if retest is not None:
                    out.append({"direction": "BEARISH", "low": c.low, "high": c.open, "source_ts": c.ts.isoformat(), "confidence": "PROBABLE_NOT_CONFIRMED"})
    return out[-limit:]


def institutional_feature_map(snapshot: MarketSnapshot) -> dict[str, Any]:
    now = snapshot.generated_at
    current = ((snapshot.bid + snapshot.ask) / 2.0) if snapshot.bid is not None and snapshot.ask is not None else snapshot.xau["M15"].bars[-1].close
    out: dict[str, Any] = {"xau": {}, "dxy": {}, "psychological_levels_xau": psychological_levels(current)}
    for market_name, group in (("xau", snapshot.xau), ("dxy", snapshot.dxy)):
        for tf, series in group.items():
            bars = closed_bars(series, now)
            av = atr(bars) if len(bars) >= 16 else (series.atr or 0.0)
            out[market_name][tf] = {
                "closed_bar_count": len(bars),
                "structure": structure_snapshot(bars),
                "fvg": fvg_list(bars, limit=6),
                "rejections": wick_rejections(bars, limit=5),
                "equal_liquidity": equal_liquidity_levels(bars, max(av * 0.08, 1e-9), lookback=min(200, len(bars))),
                "trendline_liquidity": trendline_liquidity(bars, av),
                "liquidity_sweeps": recent_liquidity_sweeps(bars),
                "breaker_blocks": probable_breaker_blocks(bars),
                "tick_volume": volume_context(bars),
                "range_state": accumulation_distribution_hint(bars, av),
                "atr_closed": av,
            }
    x_m15 = closed_bars(snapshot.xau["M15"], now)
    out["session_liquidity"] = session_liquidity(x_m15, snapshot.timezone, now)
    x_d1 = closed_bars(snapshot.xau["D1"], now)
    if x_d1:
        # If current D1 is dropped as forming, last closed D1 is the prior-day reference.
        out["prior_day"] = {"high": x_d1[-1].high, "low": x_d1[-1].low, "close": x_d1[-1].close, "ts": x_d1[-1].ts.isoformat()}
    else:
        out["prior_day"] = None
    return out
