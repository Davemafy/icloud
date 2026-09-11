from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .config import SETTINGS
from .indicators import atr, displacement_origins, equal_liquidity, recent_range, structural_bias
from .institutional_features import closed_bars, institutional_feature_map, origin_evidence
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


def _dxy_implication(xau_bias: Bias, dxy_d1: Bias, dxy_h4: Bias, dxy_h1: Bias) -> DxyImplication:
    """Conservative DXY D1/H4/H1 intermarket implication.

    H4 and H1 must agree before DXY is allowed to influence XAU execution quality.
    D1 is the macro filter: if it directly conflicts with the aligned H4/H1 leg,
    the implication is NEUTRAL rather than forcing correlation.
    """
    if xau_bias == Bias.NEUTRAL or dxy_h4 != dxy_h1 or dxy_h1 == Bias.NEUTRAL:
        return DxyImplication.NEUTRAL
    if dxy_d1 not in {Bias.NEUTRAL, dxy_h1}:
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


def _top_down_bias(d1: Bias, h4: Bias, h1: Bias) -> Bias:
    """Resolve the day bias from the same three XAU timeframes used by the manual process.

    D1 is no longer context-only. It participates in the top-down directional map, while
    H4/H1 keep enough weight to represent the active intraday leg. Mixed stacks stay
    neutral rather than forcing a trend.
    """
    directional = [b for b in (d1, h4, h1) if b != Bias.NEUTRAL]
    if not directional:
        return Bias.NEUTRAL
    if d1 == h4 == h1 and d1 != Bias.NEUTRAL:
        return d1
    if h4 == h1 and h4 != Bias.NEUTRAL:
        # Active H4/H1 leg wins only when D1 is neutral or agrees.
        return h4 if d1 in {Bias.NEUTRAL, h4} else Bias.NEUTRAL
    if d1 == h4 and d1 != Bias.NEUTRAL and h1 == Bias.NEUTRAL:
        return d1
    if d1 == h1 and d1 != Bias.NEUTRAL and h4 == Bias.NEUTRAL:
        return d1
    return Bias.NEUTRAL


def _dxy_implication_for_direction(direction: Direction, dxy_d1: Bias, dxy_h4: Bias, dxy_h1: Bias) -> DxyImplication:
    """DXY quality modifier for an individual XAU BUY/SELL zone.

    This fixes a subtle but important issue: a reversal zone must be judged against the
    DXY direction that would support *that zone*, not against the day's overall XAU bias.
    """
    if dxy_h4 != dxy_h1 or dxy_h1 == Bias.NEUTRAL:
        return DxyImplication.NEUTRAL
    if dxy_d1 not in {Bias.NEUTRAL, dxy_h1}:
        return DxyImplication.NEUTRAL
    supports = Bias.BEARISH if direction == Direction.BUY_ONLY else Bias.BULLISH
    if dxy_h1 == supports:
        return DxyImplication.SUPPORTS
    return DxyImplication.CONFLICTS


def _setup_type(direction: Direction, overall: Bias) -> str:
    wanted = _direction_bias(direction)
    if overall == Bias.NEUTRAL:
        return "TRANSITION_BUY" if direction == Direction.BUY_ONLY else "TRANSITION_SELL"
    return "CONTINUATION" if wanted == overall else "REVERSAL"


def _primary_zone_grade(
    direction: Direction,
    d1_bias: Bias,
    h4_bias: Bias,
    h1_bias: Bias,
    overall: Bias,
    zone_implication: DxyImplication,
    touches: int,
    authority_stack: list[str],
    m15_confirmation_score: int,
) -> Grade:
    """Grade a D1/H4/H1-derived XAU zone for intraday/scalp use.

    The three higher timeframes form the institutional location map. D1 supplies
    macro supply/demand and parent context; H4/H1 refine the executable price
    boundary. M15 is only a one-time quality check and M1 remains the entry authority.
    """
    wanted = _direction_bias(direction)
    if touches >= 2 or zone_implication == DxyImplication.CONFLICTS:
        return Grade.B_PLUS

    d1_ok = d1_bias in {wanted, Bias.NEUTRAL}
    h4_ok = h4_bias in {wanted, Bias.NEUTRAL}
    h1_ok = h1_bias in {wanted, Bias.NEUTRAL}
    stack = set(authority_stack)
    setup = _setup_type(direction, overall)

    # Highest-quality continuation: the same-side institutional location is visible
    # through the complete D1 -> H4 -> H1 stack and M15 already validated the POI.
    if {"D1", "H4", "H1"}.issubset(stack) and d1_ok and h4_ok and h1_ok and m15_confirmation_score >= 2:
        if touches == 0 and m15_confirmation_score >= 3 and zone_implication == DxyImplication.SUPPORTS:
            return Grade.A_PLUS
        return Grade.A

    # Two-timeframe institutional nesting remains strong enough for intraday execution.
    if len(stack.intersection({"D1", "H4", "H1"})) >= 2 and m15_confirmation_score >= 1:
        aligned_count = sum(x in {wanted, Bias.NEUTRAL} for x in (d1_bias, h4_bias, h1_bias))
        if aligned_count >= 2:
            if touches == 0 and m15_confirmation_score >= 3 and zone_implication == DxyImplication.SUPPORTS:
                return Grade.A_PLUS if setup == "CONTINUATION" else Grade.A
            return Grade.A

    # Standalone H1 may still be an intraday POI, but it cannot outrank a true
    # multi-timeframe institutional zone.
    if stack == {"H1"} and h1_bias == wanted and m15_confirmation_score >= 1:
        return Grade.A if setup == "CONTINUATION" and touches == 0 else Grade.B_PLUS

    # Counter-trend reversal is allowed only when the opposite-side zone has at least
    # two HTF authorities, is fresh, and M15/DXY do not contradict the reversal.
    if setup == "REVERSAL" and len(stack.intersection({"D1", "H4", "H1"})) >= 2:
        if touches == 0 and m15_confirmation_score >= 2 and zone_implication in {DxyImplication.SUPPORTS, DxyImplication.NEUTRAL}:
            return Grade.A

    return Grade.B_PLUS


def _zone_overlap(low1: float, high1: float, low2: float, high2: float, padding: float = 0.0) -> bool:
    return not (high1 < low2 - padding or low1 > high2 + padding)


def build_candidate_analysis(snapshot: MarketSnapshot) -> InstitutionalAnalysis:
    """Build the canonical intraday institutional map from closed HTF candles.

    Foundation contract:
      XAU D1/H4/H1      = joint institutional supply/demand authority.
      D1                = macro parent zone and external dealing-range authority.
      H4/H1             = intraday refinement and executable POI boundary.
      XAU M15           = one-time zone qualification only.
      XAU M1            = sole execution authority after publication.
      DXY D1/H4/H1      = analysis-only intermarket context.

    Critical integrity rule: MT5 supplies the forming candle, but BOS/CHoCH, FVG,
    displacement origins and HTF zones are calculated from CLOSED candles only.
    """
    missing_x = REQUIRED_XAU.difference(snapshot.xau.keys())
    missing_d = REQUIRED_DXY.difference(snapshot.dxy.keys())
    if missing_x or missing_d:
        raise ValueError(f"Missing timeframes XAU={sorted(missing_x)} DXY={sorted(missing_d)}")

    now = snapshot.generated_at
    x_d1 = closed_bars(snapshot.xau["D1"], now)
    x_h4 = closed_bars(snapshot.xau["H4"], now)
    x_h1 = closed_bars(snapshot.xau["H1"], now)
    x_m15 = closed_bars(snapshot.xau["M15"], now)
    d_d1 = closed_bars(snapshot.dxy["D1"], now)
    d_h4 = closed_bars(snapshot.dxy["H4"], now)
    d_h1 = closed_bars(snapshot.dxy["H1"], now)
    if min(map(len, (x_d1, x_h4, x_h1, x_m15, d_d1, d_h4, d_h1))) < 20:
        raise ValueError("Insufficient CLOSED candles for institutional analysis")

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
        current = snapshot.xau["M15"].bars[-1].close
    current_dxy = snapshot.dxy["H1"].bars[-1].close

    # Recompute HTF ATR from closed bars for structural calculations. The bridge ATR
    # remains useful as live broker context, but a forming candle must not alter POI geometry.
    tf_atr = {
        "D1": atr(x_d1),
        "H4": atr(x_h4),
        "H1": atr(x_h1),
        "M15": atr(x_m15),
    }
    for tf, bars in (("D1", x_d1), ("H4", x_h4), ("H1", x_h1), ("M15", x_m15)):
        if tf_atr[tf] <= 0:
            tf_atr[tf] = snapshot.xau[tf].atr or 0.0
    d1_atr = max(tf_atr["D1"], snapshot.point_size * 10)
    h4_atr = max(tf_atr["H4"], snapshot.point_size * 10)
    h1_atr = max(tf_atr["H1"], snapshot.point_size * 10)
    m15_atr = max(tf_atr["M15"], snapshot.point_size * 10)

    features = institutional_feature_map(snapshot)

    distance_cap = max(
        m15_atr * 4.0,
        min(h1_atr * SETTINGS.intraday_max_distance_h1_atr, d1_atr * SETTINGS.intraday_max_distance_d1_atr),
    )
    max_zone_width = max(
        m15_atr * SETTINGS.intraday_max_zone_width_m15_atr,
        h1_atr * 0.70,
        snapshot.point_size * 30,
    )

    d1_hi, d1_lo, d1_eq = recent_range(x_d1, min(260, len(x_d1)))
    h4_hi, h4_lo, h4_eq = recent_range(x_h4, min(120, len(x_h4)))
    h1_hi, h1_lo, h1_eq = recent_range(x_h1, min(120, len(x_h1)))
    m15_hi, m15_lo, m15_eq = recent_range(x_m15, min(96, len(x_m15)))

    # The manual process uses D1, H4 and H1 together. Do not let D1 become merely
    # decorative context; mixed top-down structure stays neutral rather than forcing a bias.
    overall = _top_down_bias(b_x_d1, b_x_h4, b_x_h1)
    implication = _dxy_implication(overall, b_d_d1, b_d_h4, b_d_h1)

    # M15 is consumed exactly once here. It can qualify an HTF location, but it can
    # never become an execution-time gate after publication.
    m15_origins: dict[Direction, list] = {}
    for direction, bias in ((Direction.BUY_ONLY, Bias.BULLISH), (Direction.SELL_ONLY, Bias.BEARISH)):
        m15_origins[direction] = displacement_origins(
            x_m15, bias, m15_atr,
            lookback=min(SETTINGS.intraday_m15_lookback, len(x_m15)),
            limit=12, body_atr_multiple=0.80,
        )

    tolerance = max(m15_atr * 0.15, snapshot.point_size * 10)
    m15_ssl = equal_liquidity(x_m15, "SSL", tolerance=tolerance, lookback=min(320, len(x_m15)))
    m15_bsl = equal_liquidity(x_m15, "BSL", tolerance=tolerance, lookback=min(320, len(x_m15)))

    def _overlap_fvg(direction: Direction, low: float, high: float):
        fvgs = features.get("xau", {}).get("M15", {}).get("fvg", [])
        wanted = "BULLISH" if direction == Direction.BUY_ONLY else "BEARISH"
        for f in fvgs:
            if f.get("direction") == wanted and not f.get("filled") and _zone_overlap(low, high, float(f["low"]), float(f["high"]), padding=m15_atr * 0.20):
                return f
        return None

    def m15_qualify(direction: Direction, low: float, high: float) -> tuple[int, list[str]]:
        wanted = _direction_bias(direction)
        padding = max(m15_atr * 0.35, snapshot.point_size * 20)
        nested = next((item for item in m15_origins[direction] if _zone_overlap(item[0], item[1], low, high, padding=padding)), None)
        aligned = b_x_m15 == wanted
        sweep_level = m15_ssl if direction == Direction.BUY_ONLY else m15_bsl
        liquidity_near = sweep_level is not None and (low - padding) <= sweep_level <= (high + padding)
        fvg = _overlap_fvg(direction, low, high)

        score = 0
        evidence: list[str] = []
        if nested is not None:
            score += 2
            evidence.append(f"M15 qualification: same-side displacement origin overlaps parent POI (origin_index={nested[2]})")
        if aligned:
            score += 1
            evidence.append(f"M15 qualification: closed-candle structure aligns {wanted.value}")
        if liquidity_near:
            score += 1
            evidence.append(f"M15 qualification: relevant {'SSL' if direction == Direction.BUY_ONLY else 'BSL'} liquidity sits at/near parent POI")
        if fvg is not None:
            score += 1
            evidence.append(f"M15 qualification: unfilled same-side FVG {float(fvg['low']):.3f}-{float(fvg['high']):.3f} overlaps parent POI")
        if score == 0:
            evidence.append("M15 qualification: no independent confirmation; zone remains B+ watch-only")
        evidence.append("M15 ROLE ENDS AT PUBLICATION; no later M15 event may delay M1 execution")
        return min(score, 3), evidence

    # Build a richer observed liquidity pool for targets. These are references only;
    # the AI cannot invent prices outside this deterministic set.
    observed_liq: list[tuple[str, float]] = []
    def add_liq(name: str, value):
        if value is not None:
            try:
                observed_liq.append((name, float(value)))
            except (TypeError, ValueError):
                pass
    add_liq("M15 range high", m15_hi); add_liq("M15 range low", m15_lo)
    add_liq("H1 range high", h1_hi); add_liq("H1 range low", h1_lo)
    add_liq("H4 range high", h4_hi); add_liq("H4 range low", h4_lo)
    add_liq("M15 equal highs", m15_bsl); add_liq("M15 equal lows", m15_ssl)
    for tf in ("H1", "H4"):
        eq = features.get("xau", {}).get(tf, {}).get("equal_liquidity", {})
        add_liq(f"{tf} equal highs", eq.get("BSL_equal_highs")); add_liq(f"{tf} equal lows", eq.get("SSL_equal_lows"))
    prior = features.get("prior_day") or {}
    add_liq("Prior-day high", prior.get("high")); add_liq("Prior-day low", prior.get("low"))
    for sess, vals in (features.get("session_liquidity") or {}).items():
        add_liq(f"{sess} high", vals.get("high")); add_liq(f"{sess} low", vals.get("low"))

    def targets(direction: Direction, low: float, high: float):
        if direction == Direction.BUY_ONLY:
            candidates = sorted({v for _, v in observed_liq if v > high})
        else:
            candidates = sorted({v for _, v in observed_liq if v < low}, reverse=True)
        return (candidates[0] if candidates else None, candidates[1] if len(candidates) > 1 else None)

    zones: List[Zone] = []
    used_h1: set[tuple[Direction, int]] = set()

    def add_zone(
        zone_id: str,
        direction: Direction,
        low: float,
        high: float,
        source_tf: str,
        source_bars,
        origin_idx: int,
        disp_idx: int,
        touch_start: int,
        authority_stack: list[str],
        provenance: list[str],
        extra_confluences: list[str] | None = None,
    ) -> None:
        midpoint = (low + high) / 2.0
        if abs(midpoint - current) > distance_cap or high - low > max_zone_width:
            return
        side_tolerance = m15_atr * 0.50
        if direction == Direction.BUY_ONLY and low > current + side_tolerance:
            return
        if direction == Direction.SELL_ONLY and high < current - side_tolerance:
            return

        touches = _touch_count_since(source_bars, low, high, touch_start)
        if touches >= 3:
            return
        if any(_zone_overlap(low, high, z.zone_low, z.zone_high, padding=m15_atr * 0.05) and z.direction == direction for z in zones):
            return

        m15_score, m15_evidence = m15_qualify(direction, low, high)
        zone_implication = _dxy_implication_for_direction(direction, b_d_d1, b_d_h4, b_d_h1)
        setup_type = _setup_type(direction, overall)
        grade = _primary_zone_grade(
            direction, b_x_d1, b_x_h4, b_x_h1, overall, zone_implication, touches, authority_stack, m15_score
        )

        wanted = _direction_bias(direction)
        ev = origin_evidence(source_bars, origin_idx, disp_idx, wanted, h1_atr if source_tf != "H4" else h4_atr)
        # Institutional source quality: a large candle alone is not enough for A/A+.
        # Require a confirmed body-close structure break and/or a same-side FVG.
        if not ev.get("bos") and not ev.get("fvg") and grade in {Grade.A, Grade.A_PLUS}:
            grade = Grade.B_PLUS

        d1_location = "discount" if midpoint <= d1_eq else "premium"
        h4_location = "discount" if midpoint <= h4_eq else "premium"
        h1_location = "discount" if midpoint <= h1_eq else "premium"
        t1, t2 = targets(direction, low, high)
        reversal = setup_type != "CONTINUATION"
        min_disp = 1.20 if reversal else 1.00
        if zone_implication == DxyImplication.CONFLICTS:
            min_disp = max(min_disp, 1.30)

        confluences = [
            f"{source_tf} CLOSED-candle displacement-origin supply/demand POI",
            f"Institutional authority stack={'>' .join(authority_stack)}",
            f"D1 {d1_location}; H4 {h4_location}; H1 {h1_location}",
            f"freshness={_freshness(touches)} touches={touches}",
            f"intraday reachability distance={abs(midpoint-current):.3f} <= cap={distance_cap:.3f}",
            f"setup={setup_type}; D1={b_x_d1.value} H4={b_x_h4.value} H1={b_x_h1.value}",
        ]
        if ev.get("bos"):
            confluences.append(f"Source displacement closed through prior structure at {float(ev['break_level']):.3f}")
        if ev.get("fvg"):
            confluences.append(f"Source displacement left FVG {float(ev['fvg']['low']):.3f}-{float(ev['fvg']['high']):.3f}")
        vr = ev.get("volume_ratio")
        if vr is not None:
            confluences.append(f"Broker tick-volume displacement ratio={vr:.2f}x vs prior median")
        confluences.extend(m15_evidence)
        if extra_confluences:
            confluences.extend(extra_confluences)
        if zone_implication == DxyImplication.SUPPORTS:
            confluences.append("DXY D1/H4/H1 intermarket implication supports this XAU zone direction")
        elif zone_implication == DxyImplication.CONFLICTS:
            confluences.append("DXY D1/H4/H1 conflicts with this XAU zone direction; B+ ceiling / stronger M1 proof required")

        # Psychological levels are confluence only, never a zone source.
        psych_candidates = sorted({v for vals in features.get("psychological_levels_xau", {}).values() for v in vals}, key=lambda v: abs(v - midpoint))
        psych = psych_candidates[0] if psych_candidates else None
        if psych is not None and abs(psych - midpoint) <= max(m15_atr * 0.25, snapshot.point_size * 50):
            confluences.append(f"XAU psychological level {psych:.2f} lies inside/near the HTF POI")
        else:
            psych = None

        if direction == Direction.BUY_ONLY:
            sweep = "SSL"
            invalidation = (
                f"Intraday invalid if CLOSED M15 price accepts below {low:.3f}: one strong candle with >="
                f"{SETTINGS.m15_zone_guard_body_beyond_pct*100:.0f}% of real body beyond the boundary and body >= "
                f"{SETTINGS.m15_zone_guard_min_body_atr:.2f}x M15 ATR, or {SETTINGS.m15_zone_guard_consecutive_closes} consecutive meaningful M15 closes beyond it. "
                "Wick-only penetration does not invalidate. H1/H4 structural retirement is reassessed on the next full analysis. "
                "M1 setup also fails if bullish sweep/MSS/displacement is negated."
            )
            invalidation_level = low
        else:
            sweep = "BSL"
            invalidation = (
                f"Intraday invalid if CLOSED M15 price accepts above {high:.3f}: one strong candle with >="
                f"{SETTINGS.m15_zone_guard_body_beyond_pct*100:.0f}% of real body beyond the boundary and body >= "
                f"{SETTINGS.m15_zone_guard_min_body_atr:.2f}x M15 ATR, or {SETTINGS.m15_zone_guard_consecutive_closes} consecutive meaningful M15 closes beyond it. "
                "Wick-only penetration does not invalidate. H1/H4 structural retirement is reassessed on the next full analysis. "
                "M1 setup also fails if bearish sweep/MSS/displacement is negated."
            )
            invalidation_level = high

        origin = source_bars[origin_idx] if 0 <= origin_idx < len(source_bars) else None
        disp = source_bars[disp_idx] if 0 <= disp_idx < len(source_bars) else None
        zones.append(Zone(
            zone_id=zone_id,
            direction=direction,
            zone_low=low,
            zone_high=high,
            grade=grade,
            source_tf=source_tf,
            setup_type=setup_type,
            authority_stack=authority_stack,
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
                "D1/H4/H1 jointly form the zone authority; H4/H1 refined the executable POI and M15 was consumed only during qualification.",
                f"M15 qualification score={m15_score}/3 frozen at publication.",
                "After publication M1 is the sole execution authority.",
                "Volume evidence is broker tick volume, not centralized exchange volume.",
                f"Classification={setup_type}; zone-specific DXY implication={zone_implication.value}.",
            ],
            provenance=provenance,
            source_candle_ts=(origin.ts if origin else None),
            source_candle_low=(origin.low if origin else None),
            source_candle_high=(origin.high if origin else None),
            displacement_ts=(disp.ts if disp else None),
            structure_break=("BOS/CHOCH_BODY_CLOSE" if ev.get("bos") else None),
            structure_break_level=ev.get("break_level"),
            fvg_low=(ev.get("fvg") or {}).get("low"),
            fvg_high=(ev.get("fvg") or {}).get("high"),
            tick_volume_ratio=ev.get("volume_ratio"),
            psychological_level=psych,
            invalidation_level=invalidation_level,
            invalidation_tf="M15",
        ))

    h4_origins: dict[Direction, list] = {}
    h1_origins: dict[Direction, list] = {}
    d1_origins: dict[Direction, list] = {}
    for direction, bias in ((Direction.BUY_ONLY, Bias.BULLISH), (Direction.SELL_ONLY, Bias.BEARISH)):
        d1_origins[direction] = displacement_origins(
            x_d1, bias, d1_atr, lookback=min(260, len(x_d1)), limit=6, body_atr_multiple=0.80
        )
        h4_origins[direction] = displacement_origins(
            x_h4, bias, h4_atr,
            lookback=min(max(240, SETTINGS.intraday_h1_lookback * 2), len(x_h4)),
            limit=8, body_atr_multiple=0.80,
        )
        h1_origins[direction] = displacement_origins(
            x_h1, bias, h1_atr,
            lookback=min(SETTINGS.intraday_h1_lookback, len(x_h1)),
            limit=12, body_atr_multiple=0.80,
        )

    # Deterministic D1/H4/H1 reference levels reproduce the manual top-down zone map.
    # D1 is now a true parent-zone authority, but intraday execution boundaries are
    # refined through H4/H1 whenever possible so the M1 EA is not handed a huge D1 box.
    def context_origin_rows(tf: str, bars, origins: dict[Direction, list], av: float):
        rows = []
        for direction in (Direction.BUY_ONLY, Direction.SELL_ONLY):
            wanted = _direction_bias(direction)
            for low, high, oi, di in origins.get(direction, []):
                ev = origin_evidence(bars, oi, di, wanted, av)
                rows.append({
                    "timeframe": tf,
                    "direction": direction.value,
                    "low": low,
                    "high": high,
                    "source_ts": ev.get("source_ts"),
                    "structure_break": bool(ev.get("bos")),
                    "break_level": ev.get("break_level"),
                    "fvg": ev.get("fvg"),
                    "tick_volume_ratio": ev.get("volume_ratio"),
                    "zone_authority": True,
                    "execution_boundary_preferred": tf in {"H4", "H1"},
                })
        return rows

    features["xau_context_levels"] = {
        "D1": context_origin_rows("D1", x_d1, d1_origins, d1_atr),
        "H4": context_origin_rows("H4", x_h4, h4_origins, h4_atr),
        "H1": context_origin_rows("H1", x_h1, h1_origins, h1_atr),
    }

    def parent_d1(direction: Direction, low: float, high: float):
        pad = max(h4_atr * 0.35, h1_atr * 0.50)
        return next((item for item in d1_origins[direction] if _zone_overlap(item[0], item[1], low, high, padding=pad)), None)

    for direction in (Direction.BUY_ONLY, Direction.SELL_ONLY):
        ordinal = 0
        pair_padding = max(h1_atr * 0.20, m15_atr * 0.50)
        for h4_low, h4_high, h4_origin_idx, h4_disp_idx in h4_origins[direction]:
            h4_mid = (h4_low + h4_high) / 2.0
            if abs(h4_mid - current) > distance_cap + h1_atr * 0.75:
                continue
            d1_parent = parent_d1(direction, h4_low, h4_high)
            nested_h1 = next((item for item in h1_origins[direction] if _zone_overlap(item[0], item[1], h4_low, h4_high, padding=pair_padding) and abs(((item[0] + item[1]) / 2.0) - current) <= distance_cap), None)
            ordinal += 1
            if nested_h1 is not None:
                h1_low, h1_high, h1_origin_idx, h1_disp_idx = nested_h1
                used_h1.add((direction, h1_origin_idx))
                if d1_parent is not None:
                    d1_low, d1_high, d1_origin_idx, _ = d1_parent
                    add_zone(
                        f"Z_D1H4H1_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                        direction, h1_low, h1_high, "D1>H4>H1", x_h1, h1_origin_idx, h1_disp_idx, h1_disp_idx + 1,
                        ["D1", "H4", "H1"],
                        [
                            f"XAU:D1:parent_supply_demand_origin:{d1_origin_idx}",
                            f"XAU:H4:parent_displacement_origin:{h4_origin_idx}",
                            f"XAU:H1:refined_supply_demand_origin:{h1_origin_idx}",
                            "XAU:M15:zone_qualification_only",
                        ],
                        [f"H1 POI refines H4 POI inside/adjacent to D1 parent zone {d1_low:.3f}-{d1_high:.3f}"],
                    )
                else:
                    add_zone(
                        f"Z_H4H1_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                        direction, h1_low, h1_high, "H4>H1", x_h1, h1_origin_idx, h1_disp_idx, h1_disp_idx + 1,
                        ["H4", "H1"],
                        [
                            f"XAU:H4:parent_displacement_origin:{h4_origin_idx}",
                            f"XAU:H1:refined_supply_demand_origin:{h1_origin_idx}",
                            "XAU:D1:top_down_context",
                            "XAU:M15:zone_qualification_only",
                        ],
                        ["H1 POI is nested in/adjacent to same-side H4 institutional POI"],
                    )
            else:
                stack = ["D1", "H4"] if d1_parent is not None else ["H4"]
                prefix = "D1H4" if d1_parent is not None else "H4"
                provenance = [f"XAU:H4:supply_demand_origin:{h4_origin_idx}", "XAU:M15:zone_qualification_only"]
                extras = ["No matching H1 refinement; retained only if compact/reachable"]
                if d1_parent is not None:
                    provenance.insert(0, f"XAU:D1:parent_supply_demand_origin:{d1_parent[2]}")
                    extras.append("H4 POI is nested in/adjacent to a same-side D1 institutional zone")
                add_zone(
                    f"Z_{prefix}_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                    direction, h4_low, h4_high, ">".join(stack), x_h4, h4_origin_idx, h4_disp_idx, h4_disp_idx + 1,
                    stack, provenance, extras,
                )

    # H1 zones not consumed by H4 refinement can still qualify. Prefer D1>H1 when
    # the H1 POI sits inside the Daily institutional source; otherwise H1 remains a
    # lower-confidence standalone intraday candidate.
    for direction in (Direction.BUY_ONLY, Direction.SELL_ONLY):
        ordinal = 0
        for h1_low, h1_high, h1_origin_idx, h1_disp_idx in h1_origins[direction]:
            if (direction, h1_origin_idx) in used_h1:
                continue
            ordinal += 1
            d1_parent = parent_d1(direction, h1_low, h1_high)
            if d1_parent is not None:
                add_zone(
                    f"Z_D1H1_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                    direction, h1_low, h1_high, "D1>H1", x_h1, h1_origin_idx, h1_disp_idx, h1_disp_idx + 1,
                    ["D1", "H1"],
                    [f"XAU:D1:parent_supply_demand_origin:{d1_parent[2]}", f"XAU:H1:supply_demand_origin:{h1_origin_idx}", "XAU:M15:zone_qualification_only"],
                    ["H1 POI refines a same-side D1 institutional zone without a separate H4 displacement origin"],
                )
            else:
                add_zone(
                    f"Z_H1_{'BUY' if direction == Direction.BUY_ONLY else 'SELL'}_{ordinal}",
                    direction, h1_low, h1_high, "H1", x_h1, h1_origin_idx, h1_disp_idx, h1_disp_idx + 1,
                    ["H1"],
                    [f"XAU:H1:supply_demand_origin:{h1_origin_idx}", "XAU:D1/H4:top_down_context", "XAU:M15:zone_qualification_only"],
                )

    # The user's manual process wants a simple two-sided day map: one best BUY area
    # and one best SELL area. In a directional day one is the continuation location
    # and the other is the reversal location. Never fabricate a missing side.
    tf_rank = {"D1>H4>H1": 0, "D1>H4": 1, "H4>H1": 2, "D1>H1": 3, "H1": 4, "H4": 5}
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 3}

    def best_for(direction: Direction):
        side = [z for z in zones if z.direction == direction]
        if not side:
            return None
        side.sort(key=lambda z: (
            grade_rank.get(z.grade, 9),
            tf_rank.get(z.source_tf, 9),
            z.touch_count,
            abs(((z.zone_low + z.zone_high) / 2.0) - current),
        ))
        return side[0]

    chosen = [best_for(Direction.BUY_ONLY), best_for(Direction.SELL_ONLY)]
    zones = [z for z in chosen if z is not None]
    zones.sort(key=lambda z: abs(((z.zone_low + z.zone_high) / 2.0) - current))

    features["two_sided_day_map"] = {
        "resolved_day_bias": overall.value,
        "buy_zone": next((z.zone_id for z in zones if z.direction == Direction.BUY_ONLY), None),
        "sell_zone": next((z.zone_id for z in zones if z.direction == Direction.SELL_ONLY), None),
        "contract": "one best BUY + one best SELL when observed evidence exists; directional day => continuation side + reversal side",
    }

    reason = None if zones else "No reachable D1/H4/H1 institutional BUY or SELL candidate survived CLOSED-candle structure, freshness, width, distance and M15-at-analysis qualification filters."
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
            reason = "Only B+ D1/H4/H1-derived watch zones are present; B+ execution is disabled."

    if snapshot.spread_points > SETTINGS.max_spread_points:
        mode = Direction.NO_TRADE
        reason = f"Spread too high: {snapshot.spread_points:.1f} points"

    history_counts = {f"XAU:{tf}": len(series.bars) for tf, series in snapshot.xau.items()}
    history_counts.update({f"DXY:{tf}": len(series.bars) for tf, series in snapshot.dxy.items()})
    atr_brief = ", ".join(f"{tf}={tf_atr[tf]:.3f}" for tf in ("D1", "H4", "H1", "M15"))

    # Identify the nearest observed liquidity objective without forcing a directional prediction.
    above = sorted((v, n) for n, v in observed_liq if v > current)
    below = sorted(((v, n) for n, v in observed_liq if v < current), reverse=True)
    if overall == Bias.BULLISH and above:
        primary_liq = f"{above[0][1]} @ {above[0][0]:.3f}"
    elif overall == Bias.BEARISH and below:
        primary_liq = f"{below[0][1]} @ {below[0][0]:.3f}"
    else:
        primary_liq = "BOTH SIDES / UNRESOLVED"

    news_brief = [
        {"title": n.title, "ts": n.ts.isoformat(), "impact": n.impact, "released": n.released, "actual": n.actual, "forecast": n.forecast, "previous": n.previous}
        for n in snapshot.news if n.currency.upper() == "USD" and n.impact.upper() == "HIGH"
    ]
    features["news_context"] = news_brief
    features["broker_context"] = {
        "bid": snapshot.bid, "ask": snapshot.ask,
        "spread_points": snapshot.spread_points, "spread_price": snapshot.spread_price,
        "bridge_atr": {tf: snapshot.xau[tf].atr for tf in ("D1", "H4", "H1", "M15")},
        "closed_bar_atr": tf_atr,
    }

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
        primary_liquidity=primary_liq,
        expected_sequence=(
            "D1/H4/H1 institutional map + DXY context -> continuation/reversal zone -> M15 qualification frozen -> zone published -> "
            "price reaches zone -> M1 liquidity sweep -> M1 MSS/CHoCH body-close + genuine displacement -> Fibonacci -> "
            "fresh M1 OB/BB/FVG -> M1 confirmation -> entry -> M1 structural SL / observed-liquidity TP -> BE -> dynamic trail"
        ),
        retail_trap=(
            "Avoid breakout chasing and wick-only structure claims. A published zone is a location, not an entry. "
            "Only M1 may trigger after the required liquidity sweep and body-close structural shift."
        ),
        overall_invalidation=(
            "For intraday execution, block new M1 entries when CLOSED M15 candles show accepted price beyond the zone distal boundary under the configured body/ATR rule; wick-only penetration is not enough. "
            "H1/H4 structural retirement is reassessed on the next full session/news analysis, or a T-10/T+10 major-news revalidation may retire/replace the zone."
        ),
        trader_brief=(
            f"{SETTINGS.trading_profile}: D1/H4/H1 jointly form the institutional zone map from CLOSED candles; H4/H1 refine the executable POI, M15 is consumed only while qualifying each zone and ends at publication; M1 executes. "
            f"History={history_counts}. Closed ATR14: {atr_brief}. Spread={snapshot.spread_points:.1f} pts. "
            f"High-impact USD events supplied={len(news_brief)}. DXY remains analysis-only."
        ),
        zones=zones,
        ea_mode=mode,
        no_trade_reason=reason,
        post_news=any(x.currency.upper() == "USD" and x.impact.upper() == "HIGH" and x.released for x in snapshot.news),
        source_fingerprint=snapshot_fingerprint(snapshot)[:24],
        approved=False,
        prompt_version="SMC_V4_2_D1_H4_H1_TWO_SIDED_MAP",
        analysis_evidence=features,
    )

def active_plan_text(analysis: InstitutionalAnalysis, zone_id: Optional[str] = None, carry_forward: bool | None = None) -> str:
    selected = None
    if zone_id:
        selected = next((z for z in analysis.zones if z.zone_id == zone_id), None)
    if selected is None:
        executable = [z for z in analysis.zones if z.grade in {Grade.A_PLUS, Grade.A} or (SETTINGS.bplus_executable and z.grade == Grade.B_PLUS)]
        rank = {Grade.A_PLUS: 3, Grade.A: 2, Grade.B_PLUS: 1, Grade.REJECT: 0}
        if executable:
            selected = sorted(executable, key=lambda z: rank[z.grade], reverse=True)[0]

    xau_zones = [z for z in analysis.zones if "XAU" in (z.instrument or "").upper() or "GOLD" in (z.instrument or "").upper()]
    if selected is not None and selected not in xau_zones:
        selected = None

    # Version 3 preserves the single selected execution zone fields used by the
    # M1 EA and exports validated XAU zones for visualization. DXY remains
    # analysis-only and is never serialized as a view/execution zone.
    refresh_due = datetime.now(timezone.utc) > analysis.valid_until.astimezone(timezone.utc)
    if carry_forward is None:
        carry_forward = SETTINGS.plan_carry_forward_until_replaced
    # Sequence EA v2.12 treats valid_until_epoch=0 as "no local hard expiry".
    # The real refresh target is still exported separately for audit/dashboard use.
    ea_expiry_epoch = 0 if carry_forward else int(analysis.valid_until.timestamp())
    lifecycle = "CARRY_FORWARD" if (carry_forward and refresh_due) else "ACTIVE"

    lines = {
        "version": "3", "analysis_id": analysis.analysis_id,
        "generated_at": analysis.generated_at.isoformat(), "valid_until": analysis.valid_until.isoformat(),
        "valid_until_epoch": str(ea_expiry_epoch),
        "refresh_due_epoch": str(int(analysis.valid_until.timestamp())),
        "refresh_due": "1" if refresh_due else "0",
        "carry_forward_until_replaced": "1" if carry_forward else "0",
        "plan_lifecycle": lifecycle, "session": analysis.session,
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
        "zone_count": str(len(xau_zones) if analysis.approved else 0),
    }

    if analysis.approved:
        for i, z in enumerate(xau_zones, start=1):
            prefix = f"view_zone_{i}_"
            lines.update({
                prefix + "instrument": z.instrument,
                prefix + "id": z.zone_id,
                prefix + "direction": z.direction.value,
                prefix + "grade": z.grade.value,
                prefix + "source_tf": z.source_tf,
                prefix + "setup_type": z.setup_type,
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
