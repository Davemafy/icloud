from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import List, Optional

from .config import SETTINGS
from .indicators import atr, displacement_origins, equal_liquidity, recent_range, structural_bias
from .models import Bias, Direction, DxyImplication, Grade, InstitutionalAnalysis, MarketSnapshot, ValidationIssue, Zone


REQUIRED_XAU = {"D1", "H4", "H1", "M15"}
REQUIRED_DXY = {"D1", "H4", "H1"}


def _bars(snapshot: MarketSnapshot, market: str, tf: str):
    src = snapshot.xau if market == "XAU" else snapshot.dxy
    if tf not in src:
        raise ValueError(f"Missing {market} {tf} bars")
    return src[tf].bars


def snapshot_fingerprint(snapshot: MarketSnapshot) -> str:
    pieces = [snapshot.generated_at.isoformat(), snapshot.session, str(snapshot.spread_points), snapshot.source]
    for market, group in (("X", snapshot.xau), ("D", snapshot.dxy)):
        for tf in sorted(group):
            b = group[tf].bars[-1]
            pieces.append(f"{market}:{tf}:{b.ts.isoformat()}:{b.close:.6f}:{b.high:.6f}:{b.low:.6f}")
    return hashlib.sha256("|".join(pieces).encode()).hexdigest()


def snapshot_id(snapshot: MarketSnapshot) -> str:
    return snapshot_fingerprint(snapshot)[:24]


def _dxy_implication(xau_bias: Bias, dxy_h4: Bias, dxy_h1: Bias) -> DxyImplication:
    """Use DXY H4 as structural context and H1 as the immediate intermarket leg.

    A directional implication is asserted only when H4 and H1 agree. Mixed DXY
    structure is deliberately NEUTRAL so the system does not overstate correlation.
    """
    if xau_bias == Bias.NEUTRAL or dxy_h4 != dxy_h1 or dxy_h1 == Bias.NEUTRAL:
        return DxyImplication.NEUTRAL
    if xau_bias == Bias.BEARISH and dxy_h1 == Bias.BULLISH:
        return DxyImplication.SUPPORTS
    if xau_bias == Bias.BULLISH and dxy_h1 == Bias.BEARISH:
        return DxyImplication.SUPPORTS
    if xau_bias == Bias.BEARISH and dxy_h1 == Bias.BEARISH:
        return DxyImplication.CONFLICTS
    if xau_bias == Bias.BULLISH and dxy_h1 == Bias.BULLISH:
        return DxyImplication.CONFLICTS
    return DxyImplication.NEUTRAL


def _touch_count(bars, low: float, high: float, lookback: int = 80) -> int:
    count = 0
    in_zone = False
    for b in bars[-lookback:]:
        touched = b.low <= high and b.high >= low
        if touched and not in_zone:
            count += 1
        in_zone = touched
    return max(0, count - 1)  # origin/formation is not counted as mitigation touch


def _freshness(touches: int) -> str:
    if touches <= 0:
        return "FRESH"
    if touches == 1:
        return "VALID"
    if touches == 2:
        return "WEAK"
    return "RETIRED"


def _touch_count_since(bars, low: float, high: float, start_index: int) -> int:
    """Count distinct mitigations after the displacement that created the zone."""
    count = 0
    in_zone = False
    for b in bars[max(0, start_index):]:
        touched = b.low <= high and b.high >= low
        if touched and not in_zone:
            count += 1
        in_zone = touched
    return count


def _direction_bias(direction: Direction) -> Bias:
    return Bias.BULLISH if direction == Direction.BUY_ONLY else Bias.BEARISH


def _zone_grade(direction: Direction, source_bias: Bias, overall: Bias, implication: DxyImplication, touches: int, source_tf: str) -> Grade:
    wanted = _direction_bias(direction)
    aligned = source_bias == wanted and (overall == wanted or overall == Bias.NEUTRAL)
    grade = Grade.A if aligned and touches <= 1 else Grade.B_PLUS
    if aligned and touches == 0 and source_tf in {"H4", "H1"} and implication == DxyImplication.SUPPORTS:
        grade = Grade.A_PLUS
    if implication == DxyImplication.CONFLICTS or touches >= 2:
        grade = Grade.B_PLUS
    return grade


def build_candidate_analysis(snapshot: MarketSnapshot) -> InstitutionalAnalysis:
    """Build a deterministic institutional map from the supplied long history.

    Numeric zone levels are always derived from observed OHLC. The AI is allowed to
    select/reject/downgrade these candidates, never invent new price levels. Candidate
    discovery intentionally covers both continuation and reversal locations so a
    neutral current bias does not automatically mean "no zones".
    """
    missing_x = REQUIRED_XAU.difference(snapshot.xau.keys())
    missing_d = REQUIRED_DXY.difference(snapshot.dxy.keys())
    if missing_x or missing_d:
        raise ValueError(f"Missing timeframes XAU={sorted(missing_x)} DXY={sorted(missing_d)}")

    x_d1 = _bars(snapshot, "XAU", "D1")
    x_h4 = _bars(snapshot, "XAU", "H4")
    x_h1 = _bars(snapshot, "XAU", "H1")
    x_m15 = _bars(snapshot, "XAU", "M15")
    d_d1 = _bars(snapshot, "DXY", "D1")
    d_h4 = _bars(snapshot, "DXY", "H4")
    d_h1 = _bars(snapshot, "DXY", "H1")

    b_x_d1 = structural_bias(x_d1)
    b_x_h4 = structural_bias(x_h4)
    b_x_h1 = structural_bias(x_h1)
    b_x_m15 = structural_bias(x_m15)
    b_d_d1 = structural_bias(d_d1)
    b_d_h4 = structural_bias(d_h4)
    b_d_h1 = structural_bias(d_h1)

    if snapshot.bid is not None and snapshot.ask is not None:
        current = (snapshot.bid + snapshot.ask) / 2.0
    else:
        current = x_m15[-1].close
    current_dxy = d_h1[-1].close

    tf_atr = {
        "D1": snapshot.xau["D1"].atr or atr(x_d1),
        "H4": snapshot.xau["H4"].atr or atr(x_h4),
        "H1": snapshot.xau["H1"].atr or atr(x_h1),
        "M15": snapshot.xau["M15"].atr or atr(x_m15),
    }
    h1_atr = max(tf_atr["H1"], snapshot.point_size * 10)
    m15_atr = max(tf_atr["M15"], snapshot.point_size * 10)
    h1_hi, h1_lo, h1_eq = recent_range(x_h1, min(160, len(x_h1)))

    bear_votes = sum(x == Bias.BEARISH for x in (b_x_h4, b_x_h1, b_x_m15))
    bull_votes = sum(x == Bias.BULLISH for x in (b_x_h4, b_x_h1, b_x_m15))
    overall = Bias.BEARISH if bear_votes >= 2 else Bias.BULLISH if bull_votes >= 2 else Bias.NEUTRAL
    implication = _dxy_implication(overall, b_d_h4, b_d_h1)

    zones: List[Zone] = []
    tf_data = {
        "D1": (x_d1, b_x_d1, 220, 2, 24.0),
        "H4": (x_h4, b_x_h4, 360, 2, 12.0),
        "H1": (x_h1, b_x_h1, 300, 3, 8.0),
    }

    for tf, (bars, source_bias, lookback, per_side, distance_mult) in tf_data.items():
        av = max(tf_atr[tf], snapshot.point_size * 10)
        for direction, bias in ((Direction.BUY_ONLY, Bias.BULLISH), (Direction.SELL_ONLY, Bias.BEARISH)):
            origins = displacement_origins(bars, bias, av, lookback=min(lookback, len(bars)), limit=per_side)
            ordinal = 0
            for low, high, origin_idx, displacement_idx in origins:
                # Institutional retracement/reversal locations must remain on the logical
                # side of current price and within a bounded HTF distance.
                if direction == Direction.BUY_ONLY and low > current + h1_atr * 0.35:
                    continue
                if direction == Direction.SELL_ONLY and high < current - h1_atr * 0.35:
                    continue
                midpoint = (low + high) / 2.0
                if abs(midpoint - current) > h1_atr * distance_mult:
                    continue
                touches = _touch_count_since(bars, low, high, displacement_idx + 1)
                if touches >= 3:
                    continue
                ordinal += 1
                grade = _zone_grade(direction, source_bias, overall, implication, touches, tf)
                premium_discount = "discount" if midpoint <= h1_eq else "premium"
                confluences = [
                    f"{tf} observed displacement origin",
                    f"{premium_discount} versus H1 dealing-range equilibrium",
                    f"freshness={_freshness(touches)} touches={touches}",
                    "M1-only execution after liquidity sweep and MSS/displacement",
                ]
                if source_bias == bias:
                    confluences.append(f"{tf} structural bias aligned")
                if implication == DxyImplication.SUPPORTS:
                    confluences.append("DXY H4/H1 intermarket implication supports direction")
                elif implication == DxyImplication.CONFLICTS:
                    confluences.append("DXY H4/H1 conflict with XAU thesis; confirmation threshold raised")

                if direction == Direction.BUY_ONLY:
                    target1 = h1_eq if h1_eq > high else h1_hi
                    target2 = h1_hi
                    sweep = "SSL"
                    invalidation = "No bullish M1 MSS/displacement after SSL sweep at the zone, or decisive acceptance below the observed origin."
                else:
                    target1 = h1_eq if h1_eq < low else h1_lo
                    target2 = h1_lo
                    sweep = "BSL"
                    invalidation = "No bearish M1 MSS/displacement after BSL sweep at the zone, or decisive acceptance above the observed origin."

                zones.append(Zone(
                    zone_id=f"Z_{tf}_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                    direction=direction,
                    zone_low=low,
                    zone_high=high,
                    grade=grade,
                    source_tf=tf,
                    touch_count=touches,
                    freshness=_freshness(touches),
                    requires_sweep=sweep,
                    min_displacement_atr=1.2 if implication == DxyImplication.CONFLICTS else 1.0,
                    min_rr=2.0,
                    target1=target1,
                    target2=target2,
                    invalidation=invalidation,
                    confluences=confluences,
                    notes=[
                        "Continuation/reversal classification is resolved by HTF context + AI selection; zone itself is observed OHLC.",
                        f"DXY implication: {implication.value}",
                    ],
                    provenance=[
                        f"XAU:{tf}:displacement_origin:{origin_idx}",
                        "XAU:H1:dealing_range",
                        f"history_count={len(bars)}",
                    ],
                ))

    # Add liquidity-based M15 reversal watch areas around equal highs/lows. These
    # remain B+ by default until AI/HTF context confirms; B+ execution stays disabled.
    tolerance = max(m15_atr * 0.15, snapshot.point_size * 10)
    ssl = equal_liquidity(x_m15, "SSL", tolerance=tolerance, lookback=min(240, len(x_m15)))
    bsl = equal_liquidity(x_m15, "BSL", tolerance=tolerance, lookback=min(240, len(x_m15)))
    if ssl is not None and ssl <= current:
        low = ssl - max(m15_atr * 0.25, snapshot.point_size * 20)
        high = ssl + max(m15_atr * 0.10, snapshot.point_size * 10)
        touches = _touch_count(x_m15, low, high, lookback=min(240, len(x_m15)))
        if touches < 3:
            zones.append(Zone(
                zone_id="Z_M15_BUY_LIQ", direction=Direction.BUY_ONLY,
                zone_low=low, zone_high=high, grade=Grade.B_PLUS, source_tf="M15/H1",
                touch_count=touches, freshness=_freshness(touches), requires_sweep="SSL",
                min_displacement_atr=1.0, min_rr=2.0, target1=h1_eq, target2=h1_hi,
                invalidation="SSL sweep fails to produce bullish M1 MSS/displacement or price accepts below the reaction area.",
                confluences=["M15 observed equal/similar lows", "H1 dealing-range relationship", "M1 reversal proof required"],
                notes=["Reversal watch zone; non-executable while B+ execution is disabled."],
                provenance=["XAU:M15:equal_liquidity:SSL", "XAU:H1:recent_range"],
            ))
    if bsl is not None and bsl >= current:
        low = bsl - max(m15_atr * 0.10, snapshot.point_size * 10)
        high = bsl + max(m15_atr * 0.25, snapshot.point_size * 20)
        touches = _touch_count(x_m15, low, high, lookback=min(240, len(x_m15)))
        if touches < 3:
            zones.append(Zone(
                zone_id="Z_M15_SELL_LIQ", direction=Direction.SELL_ONLY,
                zone_low=low, zone_high=high, grade=Grade.B_PLUS, source_tf="M15/H1",
                touch_count=touches, freshness=_freshness(touches), requires_sweep="BSL",
                min_displacement_atr=1.0, min_rr=2.0, target1=h1_eq, target2=h1_lo,
                invalidation="BSL sweep fails to produce bearish M1 MSS/displacement or price accepts above the reaction area.",
                confluences=["M15 observed equal/similar highs", "H1 dealing-range relationship", "M1 reversal proof required"],
                notes=["Reversal watch zone; non-executable while B+ execution is disabled."],
                provenance=["XAU:M15:equal_liquidity:BSL", "XAU:H1:recent_range"],
            ))

    # Stable order: nearest zones first, then HTF priority. Keep the candidate map
    # bounded so the M1 chart and AI prompt remain readable.
    tf_rank = {"D1": 0, "H4": 1, "H1": 2, "M15/H1": 3}
    zones.sort(key=lambda z: (abs(((z.zone_low + z.zone_high) / 2.0) - current), tf_rank.get(z.source_tf, 9)))
    zones = zones[:12]

    reason = None if zones else "No deterministic institutional candidate survived freshness/location filters."
    executable = [z for z in zones if z.grade in {Grade.A, Grade.A_PLUS} or (SETTINGS.bplus_executable and z.grade == Grade.B_PLUS)]
    dirs = {z.direction for z in executable}
    if dirs == {Direction.BUY_ONLY}:
        mode = Direction.BUY_ONLY
    elif dirs == {Direction.SELL_ONLY}:
        mode = Direction.SELL_ONLY
    elif Direction.BUY_ONLY in dirs and Direction.SELL_ONLY in dirs:
        mode = Direction.BUY_SELL
    else:
        mode = Direction.NO_TRADE
        if zones and reason is None:
            reason = "Only B+ watchlist zones are present; B+ execution is disabled."

    if snapshot.spread_points > SETTINGS.max_spread_points:
        mode = Direction.NO_TRADE
        reason = f"Spread too high: {snapshot.spread_points:.1f} points"

    history_counts = {f"XAU:{tf}": len(series.bars) for tf, series in snapshot.xau.items()}
    history_counts.update({f"DXY:{tf}": len(series.bars) for tf, series in snapshot.dxy.items()})
    atr_brief = ", ".join(f"{tf}={tf_atr[tf]:.3f}" for tf in ("D1", "H4", "H1", "M15"))
    now = snapshot.generated_at
    return InstitutionalAnalysis(
        analysis_id=str(uuid.uuid4()), generated_at=now,
        valid_until=now + timedelta(minutes=SETTINGS.plan_valid_minutes),
        snapshot_id=snapshot_id(snapshot), session=snapshot.session,
        current_xau_price=current, current_dxy_price=current_dxy,
        bid=snapshot.bid, ask=snapshot.ask, spread_points=snapshot.spread_points, spread_price=snapshot.spread_price,
        xau_d1_atr=tf_atr["D1"], xau_h4_atr=tf_atr["H4"], xau_h1_atr=tf_atr["H1"], xau_m15_atr=tf_atr["M15"],
        dxy_d1_bias=b_d_d1, dxy_h4_bias=b_d_h4, dxy_h1_bias=b_d_h1,
        xau_d1_bias=b_x_d1, xau_h4_bias=b_x_h4, xau_h1_bias=b_x_h1, xau_m15_context=b_x_m15,
        overall_bias=overall, dxy_implication=implication,
        primary_liquidity="SSL below current price" if overall == Bias.BEARISH else "BSL above current price" if overall == Bias.BULLISH else "BOTH SIDES / UNRESOLVED",
        expected_sequence="HTF historical context -> institutional zone -> liquidity sweep -> M1 MSS + displacement -> Fibonacci -> fresh OB/BB/FVG -> M1 confirmation -> entry -> SL/TP -> BE -> dynamic trail",
        retail_trap="Avoid breakout chasing; require the liquidity event and M1 structural proof at a qualified cloud zone.",
        overall_invalidation="A decisive higher-timeframe structural break against the selected thesis invalidates that directional framework.",
        trader_brief=f"Historical institutional map generated from {history_counts}. ATR14: {atr_brief}. Spread={snapshot.spread_points:.1f} pts. M1 remains sole execution authority.",
        zones=zones, ea_mode=mode, no_trade_reason=reason,
        post_news=any(x.currency.upper() == "USD" and x.impact.upper() == "HIGH" and x.released for x in snapshot.news),
        source_fingerprint=snapshot_fingerprint(snapshot)[:24], approved=False,
    )


def active_plan_text(analysis: InstitutionalAnalysis, zone_id: Optional[str] = None) -> str:
    selected = None
    if zone_id:
        selected = next((z for z in analysis.zones if z.zone_id == zone_id), None)
    if selected is None:
        executable = [z for z in analysis.zones if z.grade in {Grade.A_PLUS, Grade.A} or (SETTINGS.bplus_executable and z.grade == Grade.B_PLUS)]
        rank = {Grade.A_PLUS: 3, Grade.A: 2, Grade.B_PLUS: 1, Grade.REJECT: 0}
        if executable:
            selected = sorted(executable, key=lambda z: rank[z.grade], reverse=True)[0]

    # Version 3 preserves the single selected execution zone fields used by the
    # M1 EA, and additionally exports every validated cloud zone for lightweight
    # chart visualization. Watchlist B+ zones can therefore be drawn without
    # becoming executable when BPLUS_EXECUTABLE=false.
    lines = {
        "version": "3", "analysis_id": analysis.analysis_id,
        "generated_at": analysis.generated_at.isoformat(), "valid_until": analysis.valid_until.isoformat(),
        "valid_until_epoch": str(int(analysis.valid_until.timestamp())), "session": analysis.session,
        "ea_mode": analysis.ea_mode.value if analysis.approved else Direction.NO_TRADE.value,
        "approved": "1" if analysis.approved else "0", "spread_points": f"{analysis.spread_points:.1f}",
        "bid": "" if analysis.bid is None else f"{analysis.bid:.5f}",
        "ask": "" if analysis.ask is None else f"{analysis.ask:.5f}",
        "spread_price": "" if analysis.spread_price is None else f"{analysis.spread_price:.5f}",
        "atr_d1": "" if analysis.xau_d1_atr is None else f"{analysis.xau_d1_atr:.5f}",
        "atr_h4": "" if analysis.xau_h4_atr is None else f"{analysis.xau_h4_atr:.5f}",
        "atr_h1": "" if analysis.xau_h1_atr is None else f"{analysis.xau_h1_atr:.5f}",
        "atr_m15": "" if analysis.xau_m15_atr is None else f"{analysis.xau_m15_atr:.5f}",
        "dxy_implication": analysis.dxy_implication.value, "post_news": "1" if analysis.post_news else "0",
        "news_blackout": "1" if analysis.news_blackout else "0", "paper_only": "1" if SETTINGS.paper_only else "0",
        "zone_count": str(len(analysis.zones) if analysis.approved else 0),
    }

    if analysis.approved:
        for i, z in enumerate(analysis.zones, start=1):
            prefix = f"view_zone_{i}_"
            lines.update({
                prefix + "id": z.zone_id,
                prefix + "direction": z.direction.value,
                prefix + "grade": z.grade.value,
                prefix + "source_tf": z.source_tf,
                prefix + "low": f"{z.zone_low:.5f}",
                prefix + "high": f"{z.zone_high:.5f}",
                prefix + "touches": str(z.touch_count),
                prefix + "freshness": z.freshness,
                prefix + "target1": "" if z.target1 is None else f"{z.target1:.5f}",
                prefix + "target2": "" if z.target2 is None else f"{z.target2:.5f}",
                prefix + "target3": "" if z.target3 is None else f"{z.target3:.5f}",
                prefix + "runner": "" if z.runner is None else f"{z.runner:.5f}",
            })

    if selected is None or not analysis.approved or analysis.ea_mode == Direction.NO_TRADE:
        lines.update({"zone_id": "NONE", "direction": "NO_TRADE", "grade": "REJECT"})
    else:
        lines.update({
            "zone_id": selected.zone_id, "direction": selected.direction.value, "grade": selected.grade.value,
            "zone_low": f"{selected.zone_low:.5f}", "zone_high": f"{selected.zone_high:.5f}",
            "requires_sweep": selected.requires_sweep,
            "min_displacement_atr": f"{selected.min_displacement_atr:.2f}", "min_rr": f"{selected.min_rr:.2f}",
            "target1": "" if selected.target1 is None else f"{selected.target1:.5f}",
            "target2": "" if selected.target2 is None else f"{selected.target2:.5f}",
            "target3": "" if selected.target3 is None else f"{selected.target3:.5f}",
            "runner": "" if selected.runner is None else f"{selected.runner:.5f}",
        })
    return "\n".join(f"{k}={v}" for k, v in lines.items()) + "\n"


# Backwards-compatible name used by starter tests.
def analyze(snapshot: MarketSnapshot) -> InstitutionalAnalysis:
    result = build_candidate_analysis(snapshot)
    result.approved = True
    return result
