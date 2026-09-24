from __future__ import annotations

from .engine import atr
from .models import Direction, Grade, MarketSnapshot, Zone

PROMPT_SELECTION_CONTRACT = "MASTER_SNIPER_INTRADAY_SELECTION_V6587"


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _safe_atr(snapshot: MarketSnapshot) -> float:
    explicit = float(getattr(snapshot, "atr_h1", 0.0) or 0.0)
    if explicit > 0.0:
        return explicit
    bars = getattr(snapshot, "xau_h1", None) or []
    if bars:
        calculated = float(atr(bars) or 0.0)
        if calculated > 0.0:
            return calculated
    return 0.0


def _side_rank(zone: Zone, snapshot: MarketSnapshot) -> int:
    """Correct-side location is a hard selection priority, not a confluence."""
    price = float(snapshot.mid)
    lo, hi = sorted((float(zone.zone_low), float(zone.zone_high)))
    if lo <= price <= hi:
        return 0
    direction = getattr(zone, "original_direction", None)
    if direction == Direction.BUY:
        return 0 if hi < price else 1
    if direction == Direction.SELL:
        return 0 if lo > price else 1
    return 1


def _reachability(zone: Zone, snapshot: MarketSnapshot) -> tuple[int, float]:
    """Classify today's reachability without qualifying or deleting a zone."""
    h1_atr = _safe_atr(snapshot)
    distance = _distance(float(snapshot.mid), float(zone.zone_low), float(zone.zone_high))
    if h1_atr <= 0.0:
        # Missing ATR must not crash selection. Preserve deterministic proximity
        # ordering while leaving the zone in the remote/unknown reach bucket.
        return 3, distance
    distance_atr = distance / h1_atr
    if distance_atr <= 1.5:
        bucket = 0
    elif distance_atr <= 3.0:
        bucket = 1
    elif distance_atr <= 5.0:
        bucket = 2
    else:
        bucket = 3
    return bucket, distance_atr


def _source_quality(zone: Zone) -> tuple[int, int, int]:
    confluences = set(zone.confluences)
    causal = 0 if (
        "INSTITUTIONAL_DISPLACEMENT" in confluences
        or "LIQUIDITY_SWEEP_REJECTION" in confluences
    ) else 1
    fvg = 0 if "HISTORICAL_DISPLACEMENT_FVG" in confluences else 1
    volume = 0 if "TICK_VOLUME_EXPANSION" in confluences else 1
    return causal, fvg, volume


def prompt_intraday_rank(zone: Zone, snapshot: MarketSnapshot) -> tuple:
    """Rank valid zones under the Master Sniper intraday contract.

    Correct-side authority is first. A BUY above price or SELL below price cannot
    outrank a legitimate same-side zone merely because it is closer or fresher.
    After that: executable tier -> reachability -> grade -> causal source quality ->
    qualified freshness -> HTF/location quality. Raw contacts are not authority.
    """
    side_rank = _side_rank(zone, snapshot)
    execution_tier = 0 if zone.grade in {Grade.A_PLUS, Grade.A} else 1
    reach_bucket, distance_atr = _reachability(zone, snapshot)
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 9}.get(zone.grade, 9)
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(str(zone.source_tf), 9)
    causal_rank, fvg_rank, volume_rank = _source_quality(zone)
    return (
        side_rank,
        execution_tier,
        reach_bucket,
        distance_atr,
        grade_rank,
        causal_rank,
        fvg_rank,
        volume_rank,
        int(zone.touch_count),
        tf_rank,
        -float(zone.location_score),
        -int(zone.source_ts),
    )


def install_prompt_intraday_selection() -> None:
    from . import institutional_two_zone as zoning
    zoning._rank = prompt_intraday_rank
