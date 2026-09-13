from __future__ import annotations

from statistics import median
from typing import Any

from .models import Analysis, Bar, Direction, MarketSnapshot


def _tr(bars: list[Bar], i: int) -> float:
    b = bars[i]
    pc = bars[i - 1].close if i > 0 else b.close
    return max(b.high - b.low, abs(b.high - pc), abs(b.low - pc))


def _atr_slice(bars: list[Bar], n: int) -> float:
    if not bars:
        return 0.0
    start = max(0, len(bars) - n)
    vals = [_tr(bars, i) for i in range(start, len(bars))]
    return sum(vals) / max(1, len(vals))


def _efficiency(bars: list[Bar], n: int = 24) -> float:
    if len(bars) < 3:
        return 0.0
    x = bars[-min(n + 1, len(bars)) :]
    path = sum(abs(x[i].close - x[i - 1].close) for i in range(1, len(x)))
    if path <= 0:
        return 0.0
    return min(1.0, abs(x[-1].close - x[0].close) / path)


def _direction(bars: list[Bar], n: int = 24) -> Direction:
    if len(bars) < 2:
        return Direction.NEUTRAL
    x = bars[-min(n, len(bars)) :]
    delta = x[-1].close - x[0].close
    noise = sum(abs(x[i].close - x[i - 1].close) for i in range(1, len(x)))
    if noise <= 0 or abs(delta) / noise < 0.20:
        return Direction.NEUTRAL
    return Direction.BUY if delta > 0 else Direction.SELL


def _vwap_proxy(bars: list[Bar], n: int = 64) -> float:
    """Tick-volume weighted typical-price proxy.

    XAUUSD CFD tick volume is not centralized COMEX volume. This value is used only
    as an intraday fair-value proxy and never presented as exchange VWAP/order flow.
    """
    if not bars:
        return 0.0
    x = bars[-min(n, len(bars)) :]
    weighted = 0.0
    weight = 0.0
    for b in x:
        w = max(float(b.tick_volume or 0.0), 1.0)
        typical = (b.high + b.low + b.close) / 3.0
        weighted += typical * w
        weight += w
    return weighted / weight if weight > 0 else x[-1].close


def classify_regime(s: MarketSnapshot) -> dict[str, Any]:
    bars = s.xau_m15
    if len(bars) < 40:
        return {
            "name": "UNKNOWN",
            "direction": Direction.NEUTRAL.value,
            "confidence": 0.0,
            "atr_fast": 0.0,
            "atr_slow": 0.0,
            "volatility_ratio": 0.0,
            "efficiency": 0.0,
            "range_expansion": 0.0,
            "vwap_proxy": 0.0,
            "vwap_distance_atr": 0.0,
        }

    atr_fast = _atr_slice(bars, 8)
    atr_slow = _atr_slice(bars, 32)
    vol_ratio = atr_fast / atr_slow if atr_slow > 0 else 1.0
    eff = _efficiency(bars, 24)
    trend_dir = _direction(bars, 24)
    vwap = _vwap_proxy(bars, 64)
    dist_atr = abs(s.mid - vwap) / max(atr_slow, 1e-9)

    recent_ranges = [max(0.0, b.high - b.low) for b in bars[-20:]]
    med = median([x for x in recent_ranges if x > 0]) if any(x > 0 for x in recent_ranges) else 0.0
    latest_range = max(0.0, bars[-1].high - bars[-1].low)
    expansion = latest_range / med if med > 0 else 1.0

    if vol_ratio >= 1.45 and eff <= 0.28 and dist_atr >= 1.35:
        name = "EXHAUSTION"
        confidence = min(1.0, 0.45 + (vol_ratio - 1.45) * 0.30 + (dist_atr - 1.35) * 0.12)
    elif vol_ratio >= 1.22 and eff >= 0.34:
        name = "EXPANSION"
        confidence = min(1.0, 0.50 + (vol_ratio - 1.22) * 0.35 + (eff - 0.34) * 0.55)
    elif vol_ratio <= 0.76:
        name = "COMPRESSION"
        confidence = min(1.0, 0.50 + (0.76 - vol_ratio) * 0.80)
    elif eff >= 0.46:
        name = "TREND"
        confidence = min(1.0, 0.50 + (eff - 0.46) * 0.85)
    else:
        name = "RANGE"
        confidence = min(1.0, 0.55 + max(0.0, 0.38 - eff) * 0.35)

    return {
        "name": name,
        "direction": trend_dir.value,
        "confidence": round(confidence, 4),
        "atr_fast": round(atr_fast, 6),
        "atr_slow": round(atr_slow, 6),
        "volatility_ratio": round(vol_ratio, 4),
        "efficiency": round(eff, 4),
        "range_expansion": round(expansion, 4),
        "vwap_proxy": round(vwap, 6),
        "vwap_distance_atr": round(dist_atr, 4),
    }


def build_execution_overlay(s: MarketSnapshot, a: Analysis, reason: str) -> dict[str, Any]:
    regime = classify_regime(s)
    selected = next((z for z in a.zones if z.zone_id == a.selected_zone_id), None)
    if selected is None and a.zones:
        selected = a.zones[0]

    zone_dir = selected.original_direction if selected else Direction.NEUTRAL
    directional_match = (
        regime["direction"] in {Direction.NEUTRAL.value, zone_dir.value}
        if selected
        else False
    )
    continuation = bool(selected and selected.setup_type == "CONTINUATION")

    allow_momentum = bool(
        continuation and directional_match and regime["name"] in {"TREND", "EXPANSION"}
    )
    allow_vwap = bool(
        continuation and directional_match and regime["name"] == "TREND"
    )
    allow_orb = bool(
        continuation and directional_match and regime["name"] in {"TREND", "EXPANSION"}
    )

    return {
        "contract": "V6_3_SMC_LOCATION_REGIME_MULTIMODEL",
        "analysis_reason": reason,
        "regime": regime,
        "models": {
            "ict_sniper": bool(selected),
            "ict_deep_reentry": bool(selected),
            "momentum_pullback": allow_momentum,
            "vwap_proxy_reclaim": allow_vwap,
            "opening_range_retest": allow_orb,
            "accepted_zone_flip": bool(selected),
            "order_flow_imbalance": False,
        },
        "rules": {
            "htf_location_remains_authority": True,
            "alternative_primary_requires_recent_zone_interaction": True,
            "alternative_reentry_requires_original_thesis_valid": True,
            "alternative_reentry_requires_existing_position_protected": True,
            "no_model_bypasses_spread_news_snapshot_risk_guards": True,
            "vwap_is_cfd_tick_volume_proxy_not_comex_volume": True,
            "order_flow_disabled_without_centralized_feed": True,
        },
        "parameters": {
            "momentum_retrace_min": 0.30,
            "momentum_retrace_max": 0.60,
            "vwap_band_atr": 0.15,
            "opening_range_minutes": 30,
            "alternate_model_risk_multiplier": 0.75,
        },
    }


def regime_brief(overlay: dict[str, Any]) -> str:
    r = overlay.get("regime", {})
    models = overlay.get("models", {})
    enabled = [k for k, v in models.items() if v]
    return (
        f"Regime={r.get('name', 'UNKNOWN')} "
        f"dir={r.get('direction', 'NEUTRAL')} "
        f"conf={float(r.get('confidence', 0.0)):.2f}; "
        f"eligible execution models={','.join(enabled) or 'none'}."
    )
