from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from .config import SETTINGS
from .engine import (
    GRADE_RANK,
    Candidate,
    _cluster,
    _dxy,
    _location_score,
    _overlap,
    _targets,
    _touches,
    atr,
    displacement_origins,
    evaluate_zone_state,
    liquidity_map,
    structure_bias,
)
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState

TF_RANK = {"H4>H1": 0, "H1": 1, "H4": 2}

# Intraday hierarchy:
# D1 = context only
# H4/H1 = tactical zone geometry
# M15 = reachability / width / spread health
# M1 = execution (unchanged in MT5)
ACTIONABLE_MAX_H1_ATR = 3.0
PREFERRED_MAX_H1_ATR = 1.5
ZONE_MIN_M15_ATR = 0.35
ZONE_MAX_M15_ATR = 1.75


def daily_context(s: MarketSnapshot) -> Direction:
    """D1 is contextual authority only; it never defines tactical zone geometry."""
    return structure_bias(s.xau_d1)


def build_candidates(s: MarketSnapshot) -> list[Candidate]:
    """Create tactical candidates from CLOSED H4/H1 displacement origins only."""
    h4 = displacement_origins(s.xau_h4, "H4")
    h1 = displacement_origins(s.xau_h1, "H1")
    pad = max(0.01, 0.20 * (s.atr_h1 or atr(s.xau_h1)))
    out: list[Candidate] = []

    for direction in (Direction.BUY, Direction.SELL):
        H = [x for x in h4 if x.direction == direction]
        I = [x for x in h1 if x.direction == direction]

        # H1 gives practical intraday refinement. H4 overlap upgrades the candidate.
        for x in I:
            parents = [q for q in H if _overlap(q.low, q.high, x.low, x.high, pad)]
            if parents:
                h = min(
                    parents,
                    key=lambda q: abs((q.low + q.high - x.low - x.high) / 2.0),
                )
                lo, hi, method = _cluster([h, x], x)
                out.append(
                    Candidate(
                        direction,
                        lo,
                        hi,
                        "H4>H1",
                        x.source_ts,
                        method,
                        [h, x],
                    )
                )
            else:
                out.append(
                    Candidate(
                        direction,
                        x.low,
                        x.high,
                        "H1",
                        x.source_ts,
                        "H1_CONFIRMED_ORIGIN",
                        [x],
                    )
                )

        # Keep independent H4 zones only when no H1 candidate already covers them.
        for h in H:
            if any(
                c.direction == direction
                and _overlap(c.low, c.high, h.low, h.high, pad)
                for c in out
            ):
                continue
            out.append(
                Candidate(
                    direction,
                    h.low,
                    h.high,
                    "H4",
                    h.source_ts,
                    "H4_CONFIRMED_ORIGIN",
                    [h],
                )
            )
    return out


def _distance_to_zone(mid: float, low: float, high: float) -> float:
    if low <= mid <= high:
        return 0.0
    if mid < low:
        return low - mid
    return mid - high


def _zone(c: Candidate, s: MarketSnapshot, liq, context: Direction, n: int) -> Zone:
    core_mid = (c.low + c.high) / 2.0
    loc = _location_score(c.direction, core_mid, s, liq)
    h1a = s.atr_h1 or atr(s.xau_h1)
    m15a = s.atr_m15 or atr(s.xau_m15)
    h4a = atr(s.xau_h4)

    # Liquidity envelope is tactical: H1/H4 capped, never D1-sized.
    cap = max(1e-9, min(1.50 * h1a, 0.75 * h4a))
    zlo, zhi = c.low, c.high
    notes: list[str] = []

    if c.direction == Direction.SELL:
        near = [x for x in liq if x.price >= zhi and x.price - core_mid <= cap]
        if near:
            q = max(near, key=lambda x: x.price)
            zhi = max(zhi, q.price + 0.15 * m15a)
            notes.append(f"distal_liquidity:{q.label}@{q.price:.3f}")
    else:
        near = [x for x in liq if x.price <= zlo and core_mid - x.price <= cap]
        if near:
            q = min(near, key=lambda x: x.price)
            zlo = min(zlo, q.price - 0.15 * m15a)
            notes.append(f"distal_liquidity:{q.label}@{q.price:.3f}")

    # Do not leave a technically valid zone unrealistically thin versus M15 volatility.
    min_width = ZONE_MIN_M15_ATR * m15a if m15a > 0 else 0.0
    width = max(0.0, zhi - zlo)
    if min_width > 0 and width < min_width:
        extra = (min_width - width) / 2.0
        zlo -= extra
        zhi += extra
        notes.append(f"m15_min_width_expansion:{ZONE_MIN_M15_ATR:.2f}ATR")

    width = max(0.0, zhi - zlo)
    width_atr = width / max(m15a, 1e-9)
    distance = _distance_to_zone(s.mid, zlo, zhi)
    distance_h1_atr = distance / max(h1a, 1e-9)

    touches = _touches(zlo, zhi, c.source_ts, s.xau_m15)
    conf: list[str] = []

    if c.source_tf == "H4>H1":
        conf.append("H4_H1_OVERLAP")
    if any(x.fvg for x in c.components):
        conf.append("HISTORICAL_DISPLACEMENT_FVG")
    if any(x.strength >= 2 for x in c.components):
        conf.append("INSTITUTIONAL_DISPLACEMENT")
    if loc >= 7:
        conf.append("PREMIUM_DISCOUNT_EXTREMITY")
    if notes and any(x.startswith("distal_liquidity:") for x in notes):
        conf.append("EXTERNAL_LIQUIDITY_ADJACENCY")
    if ZONE_MIN_M15_ATR <= width_atr <= ZONE_MAX_M15_ATR:
        conf.append("M15_WIDTH_HEALTHY")
    if distance_h1_atr <= ACTIONABLE_MAX_H1_ATR:
        conf.append("INTRADAY_REACHABLE")

    original_targets = _targets(c.direction, core_mid, liq)
    flip = c.direction.opposite()
    flip_targets = _targets(flip, zhi if flip == Direction.BUY else zlo, liq)
    clear = abs(original_targets[0] - core_mid) if original_targets else 0.0

    counter = context not in (Direction.NEUTRAL, c.direction)
    need = (
        SETTINGS.clear_run_countertrend
        if counter
        else SETTINGS.clear_run_with_trend
    )

    unhealthy_width = width_atr > ZONE_MAX_M15_ATR
    unreachable = distance_h1_atr > ACTIONABLE_MAX_H1_ATR

    if (
        touches >= SETTINGS.zone_retire_touch_count
        or len(set(conf)) < SETTINGS.zone_min_independent_confluences
        or clear < need
        or unhealthy_width
        or unreachable
    ):
        grade = Grade.REJECT
    else:
        score = (
            (2 if c.source_tf == "H4>H1" else 1)
            + (2 if loc >= 8 else 1 if loc >= 6 else 0)
            + (1 if touches == 0 else 0)
            + (1 if "INSTITUTIONAL_DISPLACEMENT" in conf else 0)
            + (1 if distance_h1_atr <= PREFERRED_MAX_H1_ATR else 0)
            + (1 if "M15_WIDTH_HEALTHY" in conf else 0)
        )
        grade = Grade.A_PLUS if score >= 7 else Grade.A if score >= 5 else Grade.B_PLUS
        if counter and grade == Grade.A_PLUS:
            grade = Grade.A

    vals = original_targets + [0.0] * (4 - len(original_targets))
    fvals = flip_targets + [0.0] * (4 - len(flip_targets))
    inv = zhi if c.direction == Direction.SELL else zlo

    dxy = _dxy(s)
    support = (
        "NEUTRAL"
        if dxy == Direction.NEUTRAL
        else "SUPPORT"
        if (
            (c.direction == Direction.SELL and dxy == Direction.BUY)
            or (c.direction == Direction.BUY and dxy == Direction.SELL)
        )
        else "CONFLICT"
    )

    notes = [
        "D1_CONTEXT_ONLY; tactical geometry uses CLOSED H4/H1 evidence.",
        "M15 validates zone width/reachability; spread is an execution-health gate.",
        "M1 execution OB/FVG/MSS may trigger entry but cannot redefine the H4/H1 core.",
        f"reachability_h1_atr:{distance_h1_atr:.3f}",
        f"zone_width_m15_atr:{width_atr:.3f}",
        *notes,
    ]

    return Zone(
        zone_id=f"Z_{c.source_tf.replace('>','')}_{c.direction.value}_{n}",
        original_direction=c.direction,
        flip_direction=flip,
        setup_type="REVERSAL" if counter else "CONTINUATION",
        source_tf=c.source_tf,
        grade=grade,
        state=(
            ZoneState.RETIRED
            if touches >= SETTINGS.zone_retire_touch_count
            else ZoneState.ACTIVE
        ),
        core_low=round(c.low, 5),
        core_high=round(c.high, 5),
        core_method=c.method,
        location_score=loc,
        zone_low=round(zlo, 5),
        zone_high=round(zhi, 5),
        touch_count=touches,
        confluences=sorted(set(conf)),
        independent_confluence_count=len(set(conf)),
        source_ts=c.source_ts,
        invalidation_level=round(inv, 5),
        invalidation_rule=(
            "M15 accepted body beyond OUTER envelope: one >=60% body and >=0.40 ATR, "
            "or two closes each >=0.20 ATR. Wick-only does not invalidate."
        ),
        original_target1=vals[0],
        original_target2=vals[1],
        original_target3=vals[2],
        original_runner=vals[3],
        flip_target1=fvals[0],
        flip_target2=fvals[1],
        flip_target3=fvals[2],
        flip_runner=fvals[3],
        clear_run=round(clear, 5),
        countertrend=counter,
        dxy_support=support,
        notes=notes,
    )


def build_analysis(
    s: MarketSnapshot, generated_at: Optional[int] = None
) -> Analysis:
    now = generated_at or int(datetime.now(timezone.utc).timestamp())
    liq = liquidity_map(s)
    context = daily_context(s)

    zones = [
        _zone(c, s, liq, context, i + 1)
        for i, c in enumerate(build_candidates(s))
    ]
    zones = [
        z
        for z in zones
        if z.grade != Grade.REJECT and z.state != ZoneState.RETIRED
    ]

    # Rank actionable zones by grade first, then actual reachability from current price.
    best: list[Zone] = []
    for direction in (Direction.BUY, Direction.SELL):
        side = [z for z in zones if z.original_direction == direction]
        if side:
            side.sort(
                key=lambda z: (
                    GRADE_RANK[z.grade],
                    _distance_to_zone(s.mid, z.zone_low, z.zone_high)
                    / max(s.atr_h1 or atr(s.xau_h1), 1e-9),
                    TF_RANK.get(z.source_tf, 9),
                    -z.location_score,
                    z.touch_count,
                )
            )
            best.append(side[0])

    for z in best:
        z.state = evaluate_zone_state(z, s.xau_m15, s.atr_m15)

    selected = ""
    executable = [z for z in best if z.grade in (Grade.A_PLUS, Grade.A)]
    if executable:
        executable.sort(
            key=lambda z: (
                GRADE_RANK[z.grade],
                _distance_to_zone(s.mid, z.zone_low, z.zone_high)
                / max(s.atr_h1 or atr(s.xau_h1), 1e-9),
                -z.location_score,
            )
        )
        selected = executable[0].zone_id

    above = sorted(
        [x for x in liq if x.side == "ABOVE"], key=lambda x: x.distance
    )
    below = sorted(
        [x for x in liq if x.side == "BELOW"], key=lambda x: x.distance
    )
    primary = (
        above[0]
        if context == Direction.BUY and above
        else below[0]
        if context == Direction.SELL and below
        else sorted(liq, key=lambda x: x.distance)[0]
        if liq
        else None
    )

    guards: list[str] = []
    if not s.complete():
        guards.append("NO_COMPLETE_HISTORY_CONTEXT")
    if s.spread_points > SETTINGS.max_spread_points:
        guards.append(f"SPREAD_HIGH:{s.spread_points:.1f}")
    if now - s.sent_at > SETTINGS.max_snapshot_age_seconds:
        guards.append("SNAPSHOT_STALE")

    hard_block = (
        "NO_COMPLETE_HISTORY_CONTEXT" in guards
        or "SNAPSHOT_STALE" in guards
        or any(x.startswith("SPREAD_HIGH:") for x in guards)
    )

    return Analysis(
        analysis_id=f"A_{now}_{uuid.uuid4().hex[:8]}",
        generated_at=now,
        snapshot_at=s.sent_at,
        overall_bias=context,
        primary_liquidity=(
            f"{primary.label}@{primary.price:.5f}" if primary else ""
        ),
        liquidity_map=liq,
        zones=best,
        selected_zone_id=selected,
        trader_brief=(
            f"D1 context={context.value}. H4/H1 tactical zone engine; "
            f"M15 ATR/spread health; M1 execution unchanged. "
            f"DXY={_dxy(s).value} analysis-only. {len(best)} actionable two-branch zone(s)."
        ),
        approved=not hard_block,
        execution_policy={
            "core": "D1_CONTEXT_CLOSED_H4_H1_TACTICAL_M15_HEALTH",
            "primary": [
                "D1_CONTEXT",
                "H4_H1_TACTICAL_LOCATION",
                "M15_ATR_WIDTH_REACHABILITY",
                "SPREAD_HEALTH",
                "EXTERNAL_SWEEP",
                "M1_MSS_BODY_CLOSE",
                "DISPLACEMENT",
                "NEW_M1_DEALING_RANGE",
                "PREMIUM_DISCOUNT",
                "OTE_618_786",
                "FRESH_PD_ARRAY",
                "RETRACE_ENTRY",
            ],
            "reentry": [
                "THESIS_VALID",
                "OBJECTIVE_OPEN",
                "CONTINUATION_BOS",
                "NEW_DISPLACEMENT",
                "NEW_M1_DEALING_RANGE",
                "INTERNAL_LIQUIDITY",
                "PREMIUM_DISCOUNT",
                "FRESH_PD_ARRAY",
            ],
            "flip": [
                "M15_ACCEPTANCE_INVALIDATION",
                "NO_INSTANT_REVERSE",
                "OPPOSITE_SIDE_RETEST",
                "M1_MSS_BOS",
                "DISPLACEMENT",
                "NEW_M1_DEALING_RANGE",
                "PREMIUM_DISCOUNT",
                "OTE",
                "FRESH_PD_ARRAY",
            ],
            "risk": [
                "ONE_BUDGET_PER_THESIS",
                "NO_AVERAGING_DOWN",
                "NO_SL_WIDENING",
                "STRUCTURE_AWARE_BE",
                "LIQUIDITY_PARTIALS",
                "M5_ATR_RUNNER_TRAIL",
            ],
        },
        guards=guards,
    )
