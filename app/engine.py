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


def _primary_zone_grade(
    direction: Direction,
    h4_bias: Bias,
    h1_bias: Bias,
    overall: Bias,
    implication: DxyImplication,
    touches: int,
    h4_h1_pair: bool,
    m15_confirmation_score: int,
    source_tf: str,
) -> Grade:
    """Grade a H4/H1 institutional zone for intraday/scalp use.

    H4/H1 are the *location authority*. M15 is consumed here only as a zone-quality
    input. It never becomes a post-publication entry gate; once an A/A+ zone is
    published, the M1 EA may react immediately when price reaches it and the M1
    sweep/MSS/displacement sequence appears.
    """
    wanted = _direction_bias(direction)
    if touches >= 2 or implication == DxyImplication.CONFLICTS:
        return Grade.B_PLUS

    h4_ok = h4_bias in {wanted, Bias.NEUTRAL}
    h1_ok = h1_bias in {wanted, Bias.NEUTRAL}
    overall_ok = overall in {wanted, Bias.NEUTRAL}

    # Best case: the same institutional side is represented on both H4 and H1,
    # M15 confirms the POI at analysis time, the zone is fresh, and DXY supports.
    if h4_h1_pair and h4_ok and h1_ok and overall_ok and m15_confirmation_score >= 2:
        if touches == 0 and m15_confirmation_score >= 3 and implication == DxyImplication.SUPPORTS:
            return Grade.A_PLUS
        return Grade.A

    # A clean H1 demand/supply zone is valid for intraday execution when it sits
    # inside non-conflicting H4 context and has M15 qualification already present.
    if source_tf == "H1" and h1_bias == wanted and h4_ok and overall_ok and m15_confirmation_score >= 1:
        if touches == 0 and m15_confirmation_score >= 3 and implication == DxyImplication.SUPPORTS:
            return Grade.A_PLUS
        return Grade.A

    # H4-only POIs are accepted only when narrow/reachable and strongly confirmed
    # by M15. In practice the width/distance filters below eliminate swing-style POIs.
    if source_tf == "H4" and h4_bias == wanted and overall_ok and m15_confirmation_score >= 2:
        return Grade.A if touches <= 1 else Grade.B_PLUS

    # Counter-H4 intraday reversal: allow only a fresh H1 reversal zone with a
    # strong, already-observed M15 qualification and supportive DXY. M1 still has
    # to prove the reversal; M15 is not checked again at execution time.
    if source_tf == "H1" and h1_bias == wanted and h4_bias not in {wanted, Bias.NEUTRAL}:
        if touches == 0 and m15_confirmation_score >= 3 and implication == DxyImplication.SUPPORTS:
            return Grade.A

    return Grade.B_PLUS


def _zone_overlap(low1: float, high1: float, low2: float, high2: float, padding: float = 0.0) -> bool:
    return not (high1 < low2 - padding or low1 > high2 + padding)


def build_candidate_analysis(snapshot: MarketSnapshot) -> InstitutionalAnalysis:
    """Build the intraday institutional map using H4/H1 as zone authority.

    Architecture:
      D1 + DXY D1/H4/H1 = macro/intermarket context.
      XAU H4/H1         = primary supply/demand / institutional POI construction.
      XAU M15           = one-time zone qualification/refinement evidence only.
      XAU M1            = sole execution authority after the zone is published.

    No standalone M15 zone is exported. Crucially, the published plan contains no
    requirement to wait for a later M15 candle, close, displacement or confirmation.
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
    h4_atr = max(tf_atr["H4"], snapshot.point_size * 10)
    h1_atr = max(tf_atr["H1"], snapshot.point_size * 10)
    m15_atr = max(tf_atr["M15"], snapshot.point_size * 10)

    # Keep H4/H1 authority while preventing a valid-but-remote swing POI from being
    # presented as an immediate scalp zone. Reachability is a filter, not a source.
    distance_cap = max(
        m15_atr * 4.0,
        min(
            h1_atr * SETTINGS.intraday_max_distance_h1_atr,
            d1_atr * SETTINGS.intraday_max_distance_d1_atr,
        ),
    )
    # A parent H4 zone is preferably refined by H1. The remaining execution zone
    # must still be compact enough for intraday risk; M15 does not define its price.
    max_zone_width = max(
        m15_atr * SETTINGS.intraday_max_zone_width_m15_atr,
        h1_atr * 0.70,
        snapshot.point_size * 30,
    )

    h4_hi, h4_lo, h4_eq = recent_range(x_h4, min(120, len(x_h4)))
    h1_hi, h1_lo, h1_eq = recent_range(x_h1, min(120, len(x_h1)))
    m15_hi, m15_lo, m15_eq = recent_range(x_m15, min(96, len(x_m15)))

    # H4/H1, not M15, determine the immediate institutional thesis. D1 remains
    # macro context. H1 receives precedence when H4 is neutral; disagreement is
    # deliberately neutral rather than being resolved by M15.
    if b_x_h4 == b_x_h1 and b_x_h4 != Bias.NEUTRAL:
        overall = b_x_h4
    elif b_x_h4 == Bias.NEUTRAL and b_x_h1 != Bias.NEUTRAL:
        overall = b_x_h1
    elif b_x_h1 == Bias.NEUTRAL and b_x_h4 != Bias.NEUTRAL:
        overall = b_x_h4
    else:
        overall = Bias.NEUTRAL
    implication = _dxy_implication(overall, b_d_h4, b_d_h1)

    # M15 evidence is calculated once, during zone creation. It is not exported as
    # a future gate. Same-side displacement nested in the H4/H1 POI is strongest;
    # structural alignment and relevant liquidity provide additional evidence.
    m15_origins: dict[Direction, list] = {}
    for direction, bias in ((Direction.BUY_ONLY, Bias.BULLISH), (Direction.SELL_ONLY, Bias.BEARISH)):
        m15_origins[direction] = displacement_origins(
            x_m15,
            bias,
            m15_atr,
            lookback=min(SETTINGS.intraday_m15_lookback, len(x_m15)),
            limit=12,
            body_atr_multiple=0.80,
        )

    tolerance = max(m15_atr * 0.15, snapshot.point_size * 10)
    m15_ssl = equal_liquidity(x_m15, "SSL", tolerance=tolerance, lookback=min(320, len(x_m15)))
    m15_bsl = equal_liquidity(x_m15, "BSL", tolerance=tolerance, lookback=min(320, len(x_m15)))

    def m15_qualify(direction: Direction, low: float, high: float) -> tuple[int, list[str]]:
        wanted = _direction_bias(direction)
        padding = max(m15_atr * 0.35, snapshot.point_size * 20)
        nested = next(
            (item for item in m15_origins[direction] if _zone_overlap(item[0], item[1], low, high, padding=padding)),
            None,
        )
        aligned = b_x_m15 == wanted
        sweep_level = m15_ssl if direction == Direction.BUY_ONLY else m15_bsl
        liquidity_near = sweep_level is not None and (low - padding) <= sweep_level <= (high + padding)

        score = 0
        evidence: list[str] = []
        if nested is not None:
            score += 2
            evidence.append(
                f"M15 qualification: same-side displacement origin overlaps parent POI (origin_index={nested[2]}); consumed at analysis time"
            )
        if aligned:
            score += 1
            evidence.append(f"M15 qualification: structural context aligns {wanted.value}; consumed at analysis time")
        if liquidity_near:
            score += 1
            evidence.append(
                f"M15 qualification: relevant {'SSL' if direction == Direction.BUY_ONLY else 'BSL'} liquidity sits at/near parent POI; consumed at analysis time"
            )
        if score == 0:
            evidence.append("M15 qualification: no independent confirmation; zone remains watch/B+ unless other deterministic rules reject it")
        evidence.append("M15 role ENDS at zone publication; no later M15 candle/close/displacement is required for entry")
        return min(score, 3), evidence

    zones: List[Zone] = []
    used_h1: set[tuple[Direction, int]] = set()

    def targets(direction: Direction, low: float, high: float):
        # M15/H1 liquidity can provide intraday targets, but M15 is not an entry gate.
        if direction == Direction.BUY_ONLY:
            candidates = [x for x in (m15_eq, m15_hi, h1_eq, h1_hi, h4_eq) if x is not None and x > high]
            candidates = sorted(set(candidates))
        else:
            candidates = [x for x in (m15_eq, m15_lo, h1_eq, h1_lo, h4_eq) if x is not None and x < low]
            candidates = sorted(set(candidates), reverse=True)
        t1 = candidates[0] if candidates else None
        t2 = candidates[1] if len(candidates) > 1 else None
        return t1, t2

    def add_zone(
        zone_id: str,
        direction: Direction,
        low: float,
        high: float,
        source_tf: str,
        touch_bars,
        touch_start: int,
        h4_h1_pair: bool,
        provenance: list[str],
        extra_confluences: list[str] | None = None,
    ) -> None:
        midpoint = (low + high) / 2.0
        if abs(midpoint - current) > distance_cap:
            return
        if high - low > max_zone_width:
            return

        # Keep an intraday pullback POI on the logical side of price. Small overlap
        # is allowed because analysis may occur while price is already interacting.
        side_tolerance = m15_atr * 0.50
        if direction == Direction.BUY_ONLY and low > current + side_tolerance:
            return
        if direction == Direction.SELL_ONLY and high < current - side_tolerance:
            return

        touches = _touch_count_since(touch_bars, low, high, touch_start)
        if touches >= 3:
            return
        if any(
            _zone_overlap(low, high, z.zone_low, z.zone_high, padding=m15_atr * 0.05)
            and z.direction == direction
            for z in zones
        ):
            return

        m15_score, m15_evidence = m15_qualify(direction, low, high)
        grade = _primary_zone_grade(
            direction,
            b_x_h4,
            b_x_h1,
            overall,
            implication,
            touches,
            h4_h1_pair,
            m15_score,
            source_tf,
        )

        wanted = _direction_bias(direction)
        setup_type = "CONTINUATION" if overall == wanted else "REVERSAL/TRANSITION"
        h4_location = "discount" if midpoint <= h4_eq else "premium"
        h1_location = "discount" if midpoint <= h1_eq else "premium"
        t1, t2 = targets(direction, low, high)
        reversal = setup_type != "CONTINUATION"
        min_disp = 1.20 if reversal else 1.00
        if implication == DxyImplication.CONFLICTS:
            min_disp = max(min_disp, 1.30)

        confluences = [
            f"{source_tf} observed institutional displacement-origin supply/demand POI",
            f"H4 {h4_location}; H1 {h1_location}",
            f"freshness={_freshness(touches)} touches={touches}",
            f"intraday reachability distance={abs(midpoint-current):.3f} <= cap={distance_cap:.3f}",
            f"setup={setup_type}; H4={b_x_h4.value} H1={b_x_h1.value} D1={b_x_d1.value}",
        ]
        confluences.extend(m15_evidence)
        if extra_confluences:
            confluences.extend(extra_confluences)
        if implication == DxyImplication.SUPPORTS:
            confluences.append("DXY H4/H1 intermarket implication supports direction")
        elif implication == DxyImplication.CONFLICTS:
            confluences.append("DXY H4/H1 conflicts; deterministic grade ceiling is B+ and stronger M1 proof is required")

        if direction == Direction.BUY_ONLY:
            sweep = "SSL"
            invalidation = "Decisive acceptance below the H4/H1 demand POI, or failure of the required bullish M1 sweep/MSS/displacement sequence."
        else:
            sweep = "BSL"
            invalidation = "Decisive acceptance above the H4/H1 supply POI, or failure of the required bearish M1 sweep/MSS/displacement sequence."

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
                "Primary institutional zone is derived from H4/H1 supply-demand/displacement structure.",
                f"M15 qualification score={m15_score}/3 was frozen when this zone was created.",
                "After publication, M15 has NO gating/veto role. M1 may execute immediately when its own sequence is valid.",
                f"Classification={setup_type}; DXY implication={implication.value}.",
            ],
            provenance=provenance,
        ))

    # Primary zone inventory from H4 and H1 only. M15 never creates an independent
    # candidate zone. H1 nested/adjacent to an H4 POI is preferred because it keeps
    # higher-timeframe authority while making the risk box practical for a scalper.
    h4_origins: dict[Direction, list] = {}
    h1_origins: dict[Direction, list] = {}
    for direction, bias in ((Direction.BUY_ONLY, Bias.BULLISH), (Direction.SELL_ONLY, Bias.BEARISH)):
        h4_origins[direction] = displacement_origins(
            x_h4,
            bias,
            h4_atr,
            lookback=min(max(240, SETTINGS.intraday_h1_lookback * 2), len(x_h4)),
            limit=6,
            body_atr_multiple=0.80,
        )
        h1_origins[direction] = displacement_origins(
            x_h1,
            bias,
            h1_atr,
            lookback=min(SETTINGS.intraday_h1_lookback, len(x_h1)),
            limit=10,
            body_atr_multiple=0.80,
        )

    for direction in (Direction.BUY_ONLY, Direction.SELL_ONLY):
        ordinal = 0
        pair_padding = max(h1_atr * 0.20, m15_atr * 0.50)
        for h4_low, h4_high, h4_origin_idx, h4_disp_idx in h4_origins[direction]:
            h4_mid = (h4_low + h4_high) / 2.0
            if abs(h4_mid - current) > distance_cap + h1_atr * 0.75:
                continue

            nested_h1 = next(
                (
                    item
                    for item in h1_origins[direction]
                    if _zone_overlap(item[0], item[1], h4_low, h4_high, padding=pair_padding)
                    and abs(((item[0] + item[1]) / 2.0) - current) <= distance_cap
                ),
                None,
            )
            ordinal += 1
            if nested_h1 is not None:
                h1_low, h1_high, h1_origin_idx, h1_disp_idx = nested_h1
                used_h1.add((direction, h1_origin_idx))
                add_zone(
                    f"Z_INTRADAY_H4H1_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                    direction,
                    h1_low,
                    h1_high,
                    "H4>H1",
                    x_h1,
                    h1_disp_idx + 1,
                    True,
                    [
                        f"XAU:H4:parent_displacement_origin:{h4_origin_idx}",
                        f"XAU:H1:refined_supply_demand_origin:{h1_origin_idx}",
                        "XAU:M15:zone_qualification_only",
                    ],
                    ["H1 supply/demand POI is nested in/adjacent to same-side H4 institutional POI"],
                )
            else:
                # H4-only POI is retained only if it is already compact/reachable;
                # otherwise the width filter drops it rather than exporting a swing box.
                add_zone(
                    f"Z_INTRADAY_H4_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                    direction,
                    h4_low,
                    h4_high,
                    "H4",
                    x_h4,
                    h4_disp_idx + 1,
                    False,
                    [
                        f"XAU:H4:supply_demand_origin:{h4_origin_idx}",
                        "XAU:M15:zone_qualification_only",
                    ],
                    ["No matching H1 refinement; H4 POI retained only because intraday width/distance filters passed"],
                )

    # Add unused H1 institutional POIs. They remain primary zones in their own right
    # when H4 context does not conflict fatally and M15 has already qualified them.
    for direction in (Direction.BUY_ONLY, Direction.SELL_ONLY):
        ordinal = 0
        for h1_low, h1_high, h1_origin_idx, h1_disp_idx in h1_origins[direction]:
            if (direction, h1_origin_idx) in used_h1:
                continue
            ordinal += 1
            add_zone(
                f"Z_INTRADAY_H1_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                direction,
                h1_low,
                h1_high,
                "H1",
                x_h1,
                h1_disp_idx + 1,
                False,
                [
                    f"XAU:H1:supply_demand_origin:{h1_origin_idx}",
                    "XAU:H4:parent_context",
                    "XAU:M15:zone_qualification_only",
                ],
            )

    # Nearest actionable HTF POIs first. H4>H1 confluence wins tie-breaks, followed
    # by H1 and compact H4-only zones. There are intentionally no M15/M15-LIQ zones.
    tf_rank = {"H4>H1": 0, "H1": 1, "H4": 2}
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 3}
    zones.sort(
        key=lambda z: (
            grade_rank.get(z.grade, 9),
            abs(((z.zone_low + z.zone_high) / 2.0) - current),
            tf_rank.get(z.source_tf, 9),
        )
    )
    zones = zones[:max(1, SETTINGS.intraday_max_candidates)]

    reason = None if zones else "No reachable H4/H1 institutional supply-demand candidate survived freshness, width, distance and M15-at-analysis qualification filters."
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
            reason = "Only B+ H4/H1 watch zones are present; B+ execution is disabled."

    if snapshot.spread_points > SETTINGS.max_spread_points:
        mode = Direction.NO_TRADE
        reason = f"Spread too high: {snapshot.spread_points:.1f} points"

    history_counts = {f"XAU:{tf}": len(series.bars) for tf, series in snapshot.xau.items()}
    history_counts.update({f"DXY:{tf}": len(series.bars) for tf, series in snapshot.dxy.items()})
    atr_brief = ", ".join(f"{tf}={tf_atr[tf]:.3f}" for tf in ("D1", "H4", "H1", "M15"))
    now = snapshot.generated_at
    return InstitutionalAnalysis(
        analysis_id=str(uuid.uuid4()),
        generated_at=now,
        valid_until=now + timedelta(minutes=SETTINGS.plan_valid_minutes),
        snapshot_id=snapshot_id(snapshot),
        session=snapshot.session,
        current_xau_price=current,
        current_dxy_price=current_dxy,
        bid=snapshot.bid,
        ask=snapshot.ask,
        spread_points=snapshot.spread_points,
        spread_price=snapshot.spread_price,
        xau_d1_atr=tf_atr["D1"],
        xau_h4_atr=tf_atr["H4"],
        xau_h1_atr=tf_atr["H1"],
        xau_m15_atr=tf_atr["M15"],
        dxy_d1_bias=b_d_d1,
        dxy_h4_bias=b_d_h4,
        dxy_h1_bias=b_d_h1,
        xau_d1_bias=b_x_d1,
        xau_h4_bias=b_x_h4,
        xau_h1_bias=b_x_h1,
        xau_m15_context=b_x_m15,
        overall_bias=overall,
        dxy_implication=implication,
        primary_liquidity="SSL below current price" if overall == Bias.BEARISH else "BSL above current price" if overall == Bias.BULLISH else "BOTH SIDES / UNRESOLVED",
        expected_sequence=(
            "D1/DXY context -> H4/H1 institutional zone -> M15 zone qualification COMPLETE -> zone published -> "
            "price reaches zone -> M1 liquidity sweep -> M1 MSS + genuine displacement -> Fibonacci -> fresh M1 OB/BB/FVG -> "
            "M1 confirmation -> entry -> structural SL/liquidity TP -> BE -> dynamic trail"
        ),
        retail_trap=(
            "Do not chase price or wait for a new M15 signal after publication. The zone was already qualified with M15; "
            "at the POI, judge only the required M1 liquidity/MSS/displacement sequence."
        ),
        overall_invalidation=(
            "A decisive H1 structural break that invalidates the published POI, or invalidation of its H4 parent context, requires a fresh cloud analysis."
        ),
        trader_brief=(
            f"{SETTINGS.trading_profile} map generated from {history_counts}. "
            "H4/H1 are the primary institutional supply-demand/POI authority. M15 is consumed only while qualifying each zone and has no post-publication gate. "
            f"ATR14: {atr_brief}. Intraday zone distance cap={distance_cap:.3f}; width cap={max_zone_width:.3f}. "
            f"Spread={snapshot.spread_points:.1f} pts. M1 is the sole live execution authority."
        ),
        zones=zones,
        ea_mode=mode,
        no_trade_reason=reason,
        post_news=any(x.currency.upper() == "USD" and x.impact.upper() == "HIGH" and x.released for x in snapshot.news),
        source_fingerprint=snapshot_fingerprint(snapshot)[:24],
        approved=False,
        prompt_version="SMC_V3_8_H4H1_ZONE_M15_QUAL_M1_EXEC",
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
