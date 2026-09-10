from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import List, Optional

from .config import SETTINGS
from .indicators import atr, equal_liquidity, last_displacement_origin, recent_range, structural_bias
from .models import Bias, Direction, DxyImplication, Grade, InstitutionalAnalysis, MarketSnapshot, ValidationIssue, Zone


REQUIRED_XAU = {"D1", "H4", "H1", "M15"}
REQUIRED_DXY = {"D1", "H1"}


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


def _dxy_implication(xau_bias: Bias, dxy_h1: Bias) -> DxyImplication:
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


def build_candidate_analysis(snapshot: MarketSnapshot) -> InstitutionalAnalysis:
    missing_x = REQUIRED_XAU.difference(snapshot.xau.keys())
    missing_d = REQUIRED_DXY.difference(snapshot.dxy.keys())
    if missing_x or missing_d:
        raise ValueError(f"Missing timeframes XAU={sorted(missing_x)} DXY={sorted(missing_d)}")

    x_d1 = _bars(snapshot, "XAU", "D1")
    x_h4 = _bars(snapshot, "XAU", "H4")
    x_h1 = _bars(snapshot, "XAU", "H1")
    x_m15 = _bars(snapshot, "XAU", "M15")
    d_d1 = _bars(snapshot, "DXY", "D1")
    d_h1 = _bars(snapshot, "DXY", "H1")

    b_x_d1 = structural_bias(x_d1)
    b_x_h4 = structural_bias(x_h4)
    b_x_h1 = structural_bias(x_h1)
    b_x_m15 = structural_bias(x_m15)
    b_d_d1 = structural_bias(d_d1)
    b_d_h1 = structural_bias(d_h1)

    current = x_m15[-1].close
    current_dxy = d_h1[-1].close
    h1_atr = snapshot.xau["H1"].atr or atr(x_h1)
    m15_atr = snapshot.xau["M15"].atr or atr(x_m15)
    h1_hi, h1_lo, h1_eq = recent_range(x_h1, min(100, len(x_h1)))

    bear_votes = sum(x == Bias.BEARISH for x in (b_x_h4, b_x_h1, b_x_m15))
    bull_votes = sum(x == Bias.BULLISH for x in (b_x_h4, b_x_h1, b_x_m15))
    overall = Bias.BEARISH if bear_votes >= 2 else Bias.BULLISH if bull_votes >= 2 else Bias.NEUTRAL
    implication = _dxy_implication(overall, b_d_h1)

    zones: List[Zone] = []
    if overall == Bias.BEARISH:
        origin = last_displacement_origin(x_h1, Bias.BEARISH, h1_atr)
        if origin:
            touches = _touch_count(x_h1, origin[0], origin[1])
            grade = Grade.B_PLUS if implication == DxyImplication.CONFLICTS else Grade.A
            if touches >= 2:
                grade = Grade.B_PLUS
            zones.append(Zone(
                zone_id="Z_SELL_CONT",
                direction=Direction.SELL_ONLY,
                zone_low=origin[0], zone_high=origin[1],
                grade=grade, source_tf="H1",
                touch_count=touches, freshness=_freshness(touches), requires_sweep="BSL",
                min_displacement_atr=1.2 if implication == DxyImplication.CONFLICTS else 1.0,
                min_rr=2.0,
                target1=h1_eq if h1_eq < origin[0] else h1_lo,
                target2=h1_lo,
                invalidation="M1 BSL sweep fails to produce bearish MSS/displacement, the fresh bearish FVG/OB is negated, or the H1 zone is decisively reclaimed.",
                confluences=["H1 bearish displacement origin", "4H/H1 directional alignment", "M1-only execution required"],
                notes=["Do not chase displacement", f"DXY implication: {implication.value}"],
                provenance=["XAU:H1:last_displacement_origin", "XAU:H1:recent_range"],
            ))

        tolerance = max(m15_atr * 0.15, snapshot.point_size * 10)
        ssl = equal_liquidity(x_m15, "SSL", tolerance=tolerance)
        candidate = ssl if ssl is not None else h1_lo
        if current <= h1_eq:
            low = candidate - max(m15_atr * 0.25, snapshot.point_size * 20)
            high = candidate + max(m15_atr * 0.10, snapshot.point_size * 10)
            touches = _touch_count(x_m15, low, high)
            zones.append(Zone(
                zone_id="Z_BUY_REV",
                direction=Direction.BUY_ONLY,
                zone_low=low, zone_high=high,
                grade=Grade.B_PLUS, source_tf="M15/H1",
                touch_count=touches, freshness=_freshness(touches), requires_sweep="SSL",
                min_displacement_atr=1.0,
                min_rr=2.0,
                target1=h1_eq,
                target2=h1_hi,
                invalidation="No bullish M1 MSS after SSL sweep, bullish displacement is fully negated, or price accepts below the institutional reaction area.",
                confluences=["H1 discount location", "Sell-side liquidity relationship", "M1 reversal proof required"],
                notes=["Counter-trend until H1 flips", "DXY weakness can support only after M1 confirms"],
                provenance=["XAU:M15:equal_liquidity_or_H1_low", "XAU:H1:recent_range"],
            ))

    elif overall == Bias.BULLISH:
        origin = last_displacement_origin(x_h1, Bias.BULLISH, h1_atr)
        if origin:
            touches = _touch_count(x_h1, origin[0], origin[1])
            grade = Grade.B_PLUS if implication == DxyImplication.CONFLICTS or touches >= 2 else Grade.A
            zones.append(Zone(
                zone_id="Z_BUY_CONT",
                direction=Direction.BUY_ONLY,
                zone_low=origin[0], zone_high=origin[1],
                grade=grade, source_tf="H1",
                touch_count=touches, freshness=_freshness(touches), requires_sweep="SSL",
                min_displacement_atr=1.2 if implication == DxyImplication.CONFLICTS else 1.0,
                min_rr=2.0,
                target1=h1_eq if h1_eq > origin[1] else h1_hi,
                target2=h1_hi,
                invalidation="M1 SSL sweep fails to produce bullish MSS/displacement, the fresh bullish FVG/OB is negated, or the H1 zone is decisively lost.",
                confluences=["H1 bullish displacement origin", "4H/H1 directional alignment", "M1-only execution required"],
                notes=["Do not chase displacement", f"DXY implication: {implication.value}"],
                provenance=["XAU:H1:last_displacement_origin", "XAU:H1:recent_range"],
            ))

    reason = None if zones else "No qualifying deterministic institutional zone."
    if not zones:
        mode = Direction.NO_TRADE
    else:
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
            reason = "Only B+ watchlist zones are present; B+ execution is disabled."

    if snapshot.spread_points > SETTINGS.max_spread_points:
        mode = Direction.NO_TRADE
        reason = f"Spread too high: {snapshot.spread_points:.1f} points"

    now = snapshot.generated_at
    return InstitutionalAnalysis(
        analysis_id=str(uuid.uuid4()), generated_at=now,
        valid_until=now + timedelta(minutes=SETTINGS.plan_valid_minutes),
        snapshot_id=snapshot_id(snapshot), session=snapshot.session,
        current_xau_price=current, current_dxy_price=current_dxy, spread_points=snapshot.spread_points,
        dxy_d1_bias=b_d_d1, dxy_h1_bias=b_d_h1,
        xau_d1_bias=b_x_d1, xau_h4_bias=b_x_h4, xau_h1_bias=b_x_h1, xau_m15_context=b_x_m15,
        overall_bias=overall, dxy_implication=implication,
        primary_liquidity="SSL below current price" if overall == Bias.BEARISH else "BSL above current price" if overall == Bias.BULLISH else "UNRESOLVED",
        expected_sequence="HTF context -> institutional location -> liquidity sweep -> M1 MSS -> displacement -> fresh FVG/OB -> controlled pullback -> liquidity target",
        retail_trap="Avoid breakout chasing; require the liquidity event and M1 structural proof at a qualified zone.",
        overall_invalidation="A decisive higher-timeframe structural break against the current thesis invalidates the directional framework.",
        trader_brief="Deterministic candidate map generated. M1 remains the sole execution authority.",
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
