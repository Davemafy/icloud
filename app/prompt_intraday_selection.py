from __future__ import annotations

from .engine import atr
from .models import Grade, MarketSnapshot, Zone

PROMPT_SELECTION_CONTRACT = "MASTER_SNIPER_TOTAL_AUTHORITY_V6578"


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


def prompt_intraday_rank(zone: Zone, snapshot: MarketSnapshot) -> tuple:
    """Rank every already-valid Master Sniper zone symmetrically.

    BUY and SELL use the same rules. Trend and countertrend use their structural
    grades/risk matrix, but neither side receives a special price exception.
    Current-price side and reachability are relevance inputs only; they cannot erase
    an institutional source. B+ remains in the ranking tier for the agreed scaled
    risk path rather than being silently converted to research-only here.
    """
    execution_tier = 0 if zone.grade in {Grade.A_PLUS, Grade.A, Grade.B_PLUS} else 1
    reach_bucket, distance_atr = _reachability(zone, snapshot)
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 9}.get(zone.grade, 9)
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(str(zone.source_tf), 9)
    confluences = set(zone.confluences)
    return (
        execution_tier,
        reach_bucket,
        distance_atr,
        int(zone.touch_count),
        grade_rank,
        tf_rank,
        0 if "HISTORICAL_DISPLACEMENT_FVG" in confluences else 1,
        0 if "TICK_VOLUME_EXPANSION" in confluences else 1,
        -float(zone.location_score),
        -int(zone.source_ts),
    )


def install_prompt_intraday_selection() -> None:
    """Install Master Sniper selection only; never manufacture zone geometry."""
    from . import institutional_two_zone as zoning
    zoning._rank = prompt_intraday_rank
