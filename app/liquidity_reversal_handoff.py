from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .engine import atr, liquidity_map
from .execution_safety import has_live_directional_target
from .models import Analysis, Direction, Grade, MarketSnapshot, ZoneState

LIQUIDITY_REVERSAL_CONTRACT = "LIQUIDITY_REVERSAL_HANDOFF_V6519"
LOOKBACK_M15_BARS = 8
MAX_EVENT_AGE_BARS = 4
MIN_SWEEP_BUFFER_M15_ATR = 0.05
MIN_SWEEP_BUFFER_POINTS = 5.0
MIN_DISPLACEMENT_M15_ATR = 0.70
MIN_DISPLACEMENT_BODY_FRACTION = 0.55
MAX_PREZONE_DISTANCE_H1_ATR = 3.50
RISK_MULTIPLIER = 0.50

_AI_RULE = """
14. LIQUIDITY REVERSAL HANDOFF (PAPER/DEMO ONLY): a structural H1/H4/D1 liquidity pool may
    authorize M1 execution observation before the remote primary HTF core is reached only when the
    Daily context agrees with the reversal direction, the liquidity pool is outside but reasonably
    near a same-direction A/A+ primary zone, M15 has swept and rejected that pool, and a later M15
    displacement closes through nearby structure in the same direction. The liquidity pool remains a
    liquidity object; it must never be relabeled or rendered as an institutional zone. This handoff is
    not an entry. MT5 must still produce the full M1 sweep/internal-sweep -> MSS/BOS -> displacement ->
    dealing-range -> OTE/PD-array value sequence. It uses reduced paper risk and never bypasses spread,
    news, snapshot, target-direction, or account-safety guards.
"""


def install_liquidity_reversal_ai_contract() -> None:
    from . import ai

    marker = "14. LIQUIDITY REVERSAL HANDOFF"
    if marker not in ai.SYSTEM:
        ai.SYSTEM += _AI_RULE


def _inactive(reason: str) -> dict[str, Any]:
    return {
        "contract": LIQUIDITY_REVERSAL_CONTRACT,
        "active": False,
        "authority": "NONE",
        "reason": reason,
        "risk_multiplier": RISK_MULTIPLIER,
        "liquidity_remains_object_only": True,
    }


def _m15_atr(snapshot: MarketSnapshot) -> float:
    return max(float(snapshot.atr_m15 or atr(snapshot.xau_m15)), float(snapshot.point or 0.01), 1e-9)


def _h1_atr(snapshot: MarketSnapshot) -> float:
    return max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), _m15_atr(snapshot), 1e-9)


def _strong_displacement(bar, m15a: float, direction: Direction) -> bool:
    rng = max(0.0, float(bar.high) - float(bar.low))
    body = abs(float(bar.close) - float(bar.open))
    if rng < MIN_DISPLACEMENT_M15_ATR * m15a:
        return False
    if rng <= 0 or body / rng < MIN_DISPLACEMENT_BODY_FRACTION:
        return False
    return bool(
        float(bar.close) < float(bar.open)
        if direction == Direction.SELL
        else float(bar.close) > float(bar.open)
    )


def _structure_break(bars, index: int, direction: Direction) -> bool:
    if index < 2:
        return False
    prior = bars[max(0, index - 4):index]
    if not prior:
        return False
    close = float(bars[index].close)
    if direction == Direction.SELL:
        return close < min(float(b.low) for b in prior)
    return close > max(float(b.high) for b in prior)


def _context_zone(analysis: Analysis, direction: Direction):
    candidates = [
        z for z in analysis.zones
        if z.state == ZoneState.ACTIVE
        and z.original_direction == direction
        and z.grade in {Grade.A_PLUS, Grade.A, Grade.B_PLUS}
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda z: (
            0 if z.grade == Grade.A_PLUS else 1,
            0 if z.source_tf == "H4>H1" else 1 if z.source_tf == "H4" else 2,
            -float(z.location_score),
            int(z.touch_count),
        )
    )
    return candidates[0]


def _level_is_prezone(level_price: float, zone, direction: Direction, h1a: float) -> bool:
    if direction == Direction.SELL:
        distance = float(zone.zone_low) - level_price
    else:
        distance = level_price - float(zone.zone_high)
    return 0.0 < distance <= MAX_PREZONE_DISTANCE_H1_ATR * h1a


def detect_liquidity_reversal_handoff(analysis: Analysis, snapshot: MarketSnapshot) -> dict[str, Any]:
    """Detect a confirmed pre-zone liquidity reversal without manufacturing a new HTF zone."""
    if not SETTINGS.paper_only:
        return _inactive("NOT_PAPER_MODE")

    active_thesis = dict((analysis.execution_policy or {}).get("active_thesis") or {})
    if bool(active_thesis.get("locked")):
        return _inactive("ACTIVE_THESIS_OWNS_EXECUTION")

    direction = analysis.overall_bias
    if direction not in {Direction.BUY, Direction.SELL}:
        return _inactive("DAILY_CONTEXT_NEUTRAL")

    zone = _context_zone(analysis, direction)
    if zone is None:
        return _inactive("NO_SAME_DIRECTION_A_TIER_CONTEXT_ZONE")
    if str(zone.dxy_support).upper() == "CONFLICT":
        return _inactive("DXY_CONFLICT")
    if not has_live_directional_target(zone, snapshot):
        return _inactive("NO_LIVE_DIRECTIONAL_TARGET")

    bars = list(snapshot.xau_m15)
    if len(bars) < 12:
        return _inactive("INSUFFICIENT_M15_HISTORY")
    bars = bars[-max(LOOKBACK_M15_BARS + 5, 12):]
    m15a = _m15_atr(snapshot)
    h1a = _h1_atr(snapshot)
    sweep_buffer = max(
        float(snapshot.point or 0.01) * MIN_SWEEP_BUFFER_POINTS,
        MIN_SWEEP_BUFFER_M15_ATR * m15a,
    )

    # Rebuild the structural liquidity map from the latest snapshot so scheduler and
    # analysis use current levels. EQH/EQL are not zones and are never created here.
    levels = liquidity_map(snapshot)
    token = "BSL" if direction == Direction.SELL else "SSL"
    levels = [
        x for x in levels
        if token in str(x.label).upper()
        and str(x.source_tf).upper() in {"H1", "H4", "D1"}
        and _level_is_prezone(float(x.price), zone, direction, h1a)
    ]
    if not levels:
        return _inactive("NO_STRUCTURAL_PREZONE_LIQUIDITY")

    best: dict[str, Any] | None = None
    for level in levels:
        price = float(level.price)
        for i in range(max(0, len(bars) - LOOKBACK_M15_BARS), len(bars) - 1):
            bar = bars[i]
            swept = (
                float(bar.high) >= price + sweep_buffer and float(bar.close) < price
                if direction == Direction.SELL
                else float(bar.low) <= price - sweep_buffer and float(bar.close) > price
            )
            if not swept:
                continue

            for j in range(i + 1, len(bars)):
                if not _strong_displacement(bars[j], m15a, direction):
                    continue
                if not _structure_break(bars, j, direction):
                    continue
                age = (len(bars) - 1) - j
                if age > MAX_EVENT_AGE_BARS:
                    continue

                candidate = {
                    "contract": LIQUIDITY_REVERSAL_CONTRACT,
                    "active": True,
                    "authority": "LIQUIDITY_REVERSAL_HANDOFF",
                    "direction": direction.value,
                    "context_zone_id": zone.zone_id,
                    "context_zone_source_tf": zone.source_tf,
                    "liquidity_label": str(level.label),
                    "liquidity_source_tf": str(level.source_tf),
                    "liquidity_price": price,
                    "sweep_ts": int(bar.ts),
                    "displacement_ts": int(bars[j].ts),
                    "event_age_m15_bars": int(age),
                    "risk_multiplier": RISK_MULTIPLIER,
                    "requires_full_m1_sequence": True,
                    "liquidity_remains_object_only": True,
                    "zone_not_reached": True,
                    "reason": "STRUCTURAL_LIQUIDITY_SWEEP_M15_DISPLACEMENT_MSS",
                }
                if best is None or int(candidate["displacement_ts"]) > int(best["displacement_ts"]):
                    best = candidate

    return best or _inactive("NO_FRESH_CONFIRMED_LIQUIDITY_REVERSAL")


def apply_liquidity_reversal_handoff(analysis: Analysis, snapshot: MarketSnapshot) -> dict[str, Any]:
    handoff = detect_liquidity_reversal_handoff(analysis, snapshot)
    policy = dict(analysis.execution_policy or {})
    policy["liquidity_reversal_handoff"] = handoff
    analysis.execution_policy = policy

    if not bool(handoff.get("active")):
        return handoff

    context_zone_id = str(handoff.get("context_zone_id") or "")
    if context_zone_id:
        analysis.selected_zone_id = context_zone_id
    analysis.trader_brief += (
        f" PAPER LIQUIDITY_REVERSAL_HANDOFF={handoff.get('direction')} from "
        f"{handoff.get('liquidity_label')}@{float(handoff.get('liquidity_price') or 0.0):.2f}; "
        "the liquidity remains an object only, not a promoted zone. M15 sweep/rejection + displacement/MSS "
        "has opened reduced-risk M1 observation before the remote HTF core. Full M1 value confirmation is still mandatory."
    )
    return handoff
