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


def _intraday_zone_grade(
    direction: Direction,
    h1_bias: Bias,
    m15_bias: Bias,
    overall: Bias,
    implication: DxyImplication,
    touches: int,
    nested_h1: bool,
) -> Grade:
    """Grade an intraday location without turning D1/H4 swing POIs into entries.

    H1 and M15 are the location/transition layers. D1/H4 remain context. A clean
    M15 reversal against H1 can still qualify as A when DXY supports it and the
    origin is fresh; M1 must then prove the reversal with stronger displacement.
    """
    wanted = _direction_bias(direction)
    if touches >= 2 or implication == DxyImplication.CONFLICTS:
        return Grade.B_PLUS

    aligned_h1 = h1_bias == wanted
    aligned_m15 = m15_bias == wanted
    overall_ok = overall in {wanted, Bias.NEUTRAL}

    if nested_h1 and aligned_h1 and overall_ok:
        if aligned_m15 and touches == 0 and implication == DxyImplication.SUPPORTS:
            return Grade.A_PLUS
        return Grade.A

    if aligned_m15 and h1_bias in {wanted, Bias.NEUTRAL} and overall_ok:
        if aligned_h1 and touches == 0 and implication == DxyImplication.SUPPORTS:
            return Grade.A_PLUS
        return Grade.A

    # Intraday reversal exception: fresh M15 order-flow transition + supportive
    # DXY can authorize the location as A, but the EA still needs stronger M1 proof.
    if aligned_m15 and h1_bias != wanted and touches == 0 and implication == DxyImplication.SUPPORTS:
        return Grade.A

    return Grade.B_PLUS


def _zone_overlap(low1: float, high1: float, low2: float, high2: float, padding: float = 0.0) -> bool:
    return not (high1 < low2 - padding or low1 > high2 + padding)


def build_candidate_analysis(snapshot: MarketSnapshot) -> InstitutionalAnalysis:
    """Build the INTRADAY_SCALP institutional map from the supplied history.

    D1/H4 define macro/major structure and directional risk. They are deliberately
    not emitted as executable zones by default. H1 supplies the intraday framework;
    M15 supplies/refines the actual reaction locations. M1 remains the sole trigger.
    Every numeric level is still derived only from observed OHLC.
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
    d1_atr = max(tf_atr["D1"], snapshot.point_size * 10)
    h1_atr = max(tf_atr["H1"], snapshot.point_size * 10)
    m15_atr = max(tf_atr["M15"], snapshot.point_size * 10)

    # Intraday locations are bounded by both immediate H1 volatility and the
    # current daily volatility envelope. This removes far-away swing POIs such as
    # zones several H1 ATRs from current price.
    distance_cap = max(
        m15_atr * 4.0,
        min(
            h1_atr * SETTINGS.intraday_max_distance_h1_atr,
            d1_atr * SETTINGS.intraday_max_distance_d1_atr,
        ),
    )
    max_zone_width = max(m15_atr * SETTINGS.intraday_max_zone_width_m15_atr, snapshot.point_size * 30)

    h1_hi, h1_lo, h1_eq = recent_range(x_h1, min(96, len(x_h1)))
    m15_hi, m15_lo, m15_eq = recent_range(x_m15, min(64, len(x_m15)))

    bear_votes = sum(x == Bias.BEARISH for x in (b_x_h4, b_x_h1, b_x_m15))
    bull_votes = sum(x == Bias.BULLISH for x in (b_x_h4, b_x_h1, b_x_m15))
    overall = Bias.BEARISH if bear_votes >= 2 else Bias.BULLISH if bull_votes >= 2 else Bias.NEUTRAL
    implication = _dxy_implication(overall, b_d_h4, b_d_h1)

    zones: List[Zone] = []

    def targets(direction: Direction, low: float, high: float):
        if direction == Direction.BUY_ONLY:
            t1 = m15_eq if m15_eq > high else m15_hi
            t2 = h1_eq if h1_eq > t1 else h1_hi
            if t1 <= high:
                t1 = None
            if t2 is not None and t2 <= (t1 if t1 is not None else high):
                t2 = None
            return t1, t2
        t1 = m15_eq if m15_eq < low else m15_lo
        t2 = h1_eq if h1_eq < t1 else h1_lo
        if t1 >= low:
            t1 = None
        if t2 is not None and t2 >= (t1 if t1 is not None else low):
            t2 = None
        return t1, t2

    def add_zone(
        zone_id: str,
        direction: Direction,
        low: float,
        high: float,
        source_tf: str,
        touch_bars,
        touch_start: int,
        nested_h1: bool,
        provenance: list[str],
        extra_confluences: list[str] | None = None,
    ) -> None:
        midpoint = (low + high) / 2.0
        if abs(midpoint - current) > distance_cap:
            return
        if high - low > max_zone_width:
            return
        # A pullback/scalp POI may overlap current price, but a buy zone should not
        # sit materially above it and a sell zone should not sit materially below it.
        side_tolerance = m15_atr * 0.50
        if direction == Direction.BUY_ONLY and low > current + side_tolerance:
            return
        if direction == Direction.SELL_ONLY and high < current - side_tolerance:
            return

        touches = _touch_count_since(touch_bars, low, high, touch_start)
        if touches >= 3:
            return
        if any(_zone_overlap(low, high, z.zone_low, z.zone_high, padding=m15_atr * 0.05) and z.direction == direction for z in zones):
            return

        grade = _intraday_zone_grade(direction, b_x_h1, b_x_m15, overall, implication, touches, nested_h1)
        wanted = _direction_bias(direction)
        setup_type = "CONTINUATION" if b_x_h1 == wanted else "REVERSAL/TRANSITION"
        local_location = "discount" if midpoint <= m15_eq else "premium"
        h1_location = "discount" if midpoint <= h1_eq else "premium"
        t1, t2 = targets(direction, low, high)
        reversal = setup_type != "CONTINUATION"
        min_disp = 1.20 if reversal else 1.00
        if implication == DxyImplication.CONFLICTS:
            min_disp = max(min_disp, 1.30)

        confluences = [
            f"{source_tf} observed displacement origin/refinement",
            f"M15 {local_location}; H1 {h1_location}",
            f"freshness={_freshness(touches)} touches={touches}",
            f"profile={SETTINGS.trading_profile}; distance={abs(midpoint-current):.3f} <= cap={distance_cap:.3f}",
            f"setup={setup_type}",
            f"HTF context D1={b_x_d1.value} H4={b_x_h4.value} H1={b_x_h1.value} M15={b_x_m15.value}",
            "M1-only execution after liquidity sweep, MSS and genuine displacement",
        ]
        if extra_confluences:
            confluences.extend(extra_confluences)
        if implication == DxyImplication.SUPPORTS:
            confluences.append("DXY H4/H1 intermarket implication supports direction")
        elif implication == DxyImplication.CONFLICTS:
            confluences.append("DXY H4/H1 conflict; stronger M1 displacement required")

        if direction == Direction.BUY_ONLY:
            sweep = "SSL"
            invalidation = "No bullish M1 MSS/displacement after SSL sweep at the intraday zone, or decisive acceptance below the observed origin."
        else:
            sweep = "BSL"
            invalidation = "No bearish M1 MSS/displacement after BSL sweep at the intraday zone, or decisive acceptance above the observed origin."

        zones.append(Zone(
            zone_id=zone_id,
            direction=direction,
            zone_low=low,
            zone_high=high,
            grade=grade,
            source_tf=source_tf,
            touch_count=touches,
            freshness=_freshness(touches),
            requires_sweep=sweep,
            min_displacement_atr=min_disp,
            min_rr=2.0,
            target1=t1,
            target2=t2,
            invalidation=invalidation,
            confluences=confluences,
            notes=[
                "Intraday/scalping execution zone; D1/H4 are context, not a distant swing-entry mandate.",
                f"Classification={setup_type}. M1 trigger remains mandatory.",
                f"DXY implication={implication.value}.",
            ],
            provenance=provenance,
        ))

    # Cache recent M15 displacement origins. They are the primary intraday POIs
    # and also serve as refinements nested within a nearby H1 displacement origin.
    m15_origins: dict[Direction, list] = {}
    for direction, bias in ((Direction.BUY_ONLY, Bias.BULLISH), (Direction.SELL_ONLY, Bias.BEARISH)):
        m15_origins[direction] = displacement_origins(
            x_m15,
            bias,
            m15_atr,
            lookback=min(SETTINGS.intraday_m15_lookback, len(x_m15)),
            limit=10,
            body_atr_multiple=0.80,
        )

    # H1 establishes the intraday framework. Prefer a nested M15 origin as the
    # actual zone boundary; use the H1 body only when it is already narrow enough.
    for direction, bias in ((Direction.BUY_ONLY, Bias.BULLISH), (Direction.SELL_ONLY, Bias.BEARISH)):
        h1_origins = displacement_origins(
            x_h1,
            bias,
            h1_atr,
            lookback=min(SETTINGS.intraday_h1_lookback, len(x_h1)),
            limit=5,
            body_atr_multiple=0.80,
        )
        ordinal = 0
        for h1_low, h1_high, h1_origin_idx, h1_disp_idx in h1_origins:
            h1_mid = (h1_low + h1_high) / 2.0
            if abs(h1_mid - current) > distance_cap + h1_atr * 0.25:
                continue
            padding = max(m15_atr * 0.50, h1_atr * 0.10)
            nested = next(
                (
                    item for item in m15_origins[direction]
                    if _zone_overlap(item[0], item[1], h1_low, h1_high, padding=padding)
                    and abs(((item[0] + item[1]) / 2.0) - current) <= distance_cap
                ),
                None,
            )
            ordinal += 1
            if nested is not None:
                low, high, m15_origin_idx, m15_disp_idx = nested
                add_zone(
                    f"Z_SCALP_H1M15_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                    direction, low, high, "H1>M15", x_m15, m15_disp_idx + 1, True,
                    [
                        f"XAU:H1:displacement_origin:{h1_origin_idx}",
                        f"XAU:M15:refinement_origin:{m15_origin_idx}",
                        "XAU:M15:intraday_dealing_range",
                    ],
                    ["M15 origin nested in/adjacent to observed H1 institutional origin"],
                )
            else:
                add_zone(
                    f"Z_SCALP_H1_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                    direction, h1_low, h1_high, "H1", x_h1, h1_disp_idx + 1, True,
                    [f"XAU:H1:displacement_origin:{h1_origin_idx}", "XAU:M15:intraday_dealing_range"],
                    ["No clean nested M15 origin found; H1 body retained only if intraday width/distance filters pass"],
                )

    # Add nearby M15 displacement origins directly. These supply continuation and
    # transition/reversal scalp locations even when no H1 body nests perfectly.
    for direction in (Direction.BUY_ONLY, Direction.SELL_ONLY):
        ordinal = 0
        for low, high, origin_idx, displacement_idx in m15_origins[direction]:
            ordinal += 1
            add_zone(
                f"Z_SCALP_M15_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                direction, low, high, "M15", x_m15, displacement_idx + 1, False,
                [f"XAU:M15:displacement_origin:{origin_idx}", "XAU:H1:intraday_framework"],
            )

    # Equal-liquidity areas stay visible as B+ watch zones. They are useful for a
    # scalper because the sweep itself may create the M1 event, but they do not
    # become executable unless the configured B+ policy is explicitly enabled.
    tolerance = max(m15_atr * 0.15, snapshot.point_size * 10)
    ssl = equal_liquidity(x_m15, "SSL", tolerance=tolerance, lookback=min(240, len(x_m15)))
    bsl = equal_liquidity(x_m15, "BSL", tolerance=tolerance, lookback=min(240, len(x_m15)))
    if ssl is not None and ssl <= current and abs(ssl - current) <= distance_cap:
        low = ssl - max(m15_atr * 0.25, snapshot.point_size * 20)
        high = ssl + max(m15_atr * 0.10, snapshot.point_size * 10)
        touches = _touch_count(x_m15, low, high, lookback=min(240, len(x_m15)))
        if touches < 3 and high - low <= max_zone_width:
            zones.append(Zone(
                zone_id="Z_SCALP_M15_BUY_LIQ", direction=Direction.BUY_ONLY,
                zone_low=low, zone_high=high, grade=Grade.B_PLUS, source_tf="M15-LIQ",
                touch_count=touches, freshness=_freshness(touches), requires_sweep="SSL",
                min_displacement_atr=1.20, min_rr=2.0, target1=m15_eq if m15_eq > high else m15_hi, target2=h1_eq if h1_eq > high else h1_hi,
                invalidation="SSL sweep fails to produce bullish M1 MSS/displacement or price accepts below the reaction area.",
                confluences=["M15 equal/similar lows", "intraday distance filter passed", "M1 reversal proof required"],
                notes=["Intraday reversal watch zone; B+ remains non-executable by default."],
                provenance=["XAU:M15:equal_liquidity:SSL", "XAU:H1:intraday_framework"],
            ))
    if bsl is not None and bsl >= current and abs(bsl - current) <= distance_cap:
        low = bsl - max(m15_atr * 0.10, snapshot.point_size * 10)
        high = bsl + max(m15_atr * 0.25, snapshot.point_size * 20)
        touches = _touch_count(x_m15, low, high, lookback=min(240, len(x_m15)))
        if touches < 3 and high - low <= max_zone_width:
            zones.append(Zone(
                zone_id="Z_SCALP_M15_SELL_LIQ", direction=Direction.SELL_ONLY,
                zone_low=low, zone_high=high, grade=Grade.B_PLUS, source_tf="M15-LIQ",
                touch_count=touches, freshness=_freshness(touches), requires_sweep="BSL",
                min_displacement_atr=1.20, min_rr=2.0, target1=m15_eq if m15_eq < low else m15_lo, target2=h1_eq if h1_eq < low else h1_lo,
                invalidation="BSL sweep fails to produce bearish M1 MSS/displacement or price accepts above the reaction area.",
                confluences=["M15 equal/similar highs", "intraday distance filter passed", "M1 reversal proof required"],
                notes=["Intraday reversal watch zone; B+ remains non-executable by default."],
                provenance=["XAU:M15:equal_liquidity:BSL", "XAU:H1:intraday_framework"],
            ))

    # Nearest intraday locations first. H1>M15 refinements win tie-breaks, followed
    # by H1 and direct M15. D1/H4 are intentionally absent from the plotted map.
    tf_rank = {"H1>M15": 0, "H1": 1, "M15": 2, "M15-LIQ": 3}
    zones.sort(key=lambda z: (abs(((z.zone_low + z.zone_high) / 2.0) - current), tf_rank.get(z.source_tf, 9)))
    zones = zones[:max(1, SETTINGS.intraday_max_candidates)]

    reason = None if zones else "No nearby intraday institutional candidate survived H1/M15 freshness, width and ATR-distance filters."
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
            reason = "Only B+ intraday watch zones are present; B+ execution is disabled."

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
        expected_sequence="D1/H4 context -> H1/M15 intraday location -> liquidity sweep -> M1 MSS + displacement -> Fibonacci -> fresh OB/BB/FVG -> M1 confirmation -> entry -> SL/TP -> BE -> dynamic trail",
        retail_trap="Avoid chasing current price. Wait for price to trade into a nearby session-relevant H1/M15 institutional location and prove the M1 liquidity event.",
        overall_invalidation="A decisive H1 structural break against the intraday thesis, or invalidation of its parent H4 context, requires a fresh analysis.",
        trader_brief=(
            f"{SETTINGS.trading_profile} institutional map generated from {history_counts}. "
            f"D1/H4 are context only; H1/M15 create plotted execution locations. "
            f"ATR14: {atr_brief}. Intraday zone distance cap={distance_cap:.3f}. "
            f"Spread={snapshot.spread_points:.1f} pts. M1 remains sole execution authority."
        ),
        zones=zones, ea_mode=mode, no_trade_reason=reason,
        post_news=any(x.currency.upper() == "USD" and x.impact.upper() == "HIGH" and x.released for x in snapshot.news),
        source_fingerprint=snapshot_fingerprint(snapshot)[:24], approved=False,
        prompt_version="SMC_V3_7_INTRADAY_SCALP",
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
        "trading_profile": SETTINGS.trading_profile,
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
