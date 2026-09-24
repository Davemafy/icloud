from __future__ import annotations

from .engine import atr
from .models import Grade, MarketSnapshot, Zone

PROMPT_SELECTION_CONTRACT = "MASTER_SNIPER_INTRADAY_SELECTION_V6583"


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _reachability(zone: Zone, snapshot: MarketSnapshot) -> tuple[int, float]:
    """Classify today's reachability without qualifying or deleting a zone."""
    h1_atr = max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9)
    distance = _distance(float(snapshot.mid), float(zone.zone_low), float(zone.zone_high))
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
    """Prefer the institutional event that actually created the move.

    The Master Sniper map is source-candle first. A nearer minor interaction must
    not outrank a genuine displacement/BOS or sweep-rejection source merely because
    it has fewer historical contacts. FVG and volume remain supporting evidence,
    never standalone zone factories.
    """
    confluences = set(zone.confluences)
    causal = 0 if (
        "INSTITUTIONAL_DISPLACEMENT" in confluences
        or "LIQUIDITY_SWEEP_REJECTION" in confluences
    ) else 1
    fvg = 0 if "HISTORICAL_DISPLACEMENT_FVG" in confluences else 1
    volume = 0 if "TICK_VOLUME_EXPANSION" in confluences else 1
    return causal, fvg, volume


def prompt_intraday_rank(zone: Zone, snapshot: MarketSnapshot) -> tuple:
    """Rank already-valid zones by the Master Sniper intraday contract.

    Order is deliberate:
      1) executable structural tier,
      2) today's reachability,
      3) current execution grade,
      4) causal source quality,
      5) qualified mitigation freshness,
      6) HTF authority and location quality.

    Raw contacts never appear here. Qualified mitigation is already incorporated
    into current execution grade, so touch count is only a later same-grade
    tiebreaker. This prevents a weak/less important zero-touch zone from displacing
    the A+/A institutional source the trader would actually mark on H4/H1.
    """
    execution_tier = 0 if zone.grade in {Grade.A_PLUS, Grade.A} else 1
    reach_bucket, distance_atr = _reachability(zone, snapshot)
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 9}.get(zone.grade, 9)
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(str(zone.source_tf), 9)
    causal_rank, fvg_rank, volume_rank = _source_quality(zone)
    return (
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
    """Install selection only; source/liquidity/M15/M1 rules are unchanged."""
    from . import institutional_two_zone as zoning

    zoning._rank = prompt_intraday_rank
