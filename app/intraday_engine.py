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

ACTIONABLE_MAX_H1_ATR = 2.50
WATCH_MAX_H1_ATR = 5.00
CONTEXT_MAX_H1_ATR = 8.00
PREFERRED_MAX_H1_ATR = 1.50
ZONE_MIN_M15_ATR = 0.45
ACTIONABLE_MAX_M15_ATR = 3.00
WATCH_MAX_M15_ATR = 6.00
INTRADAY_RETIRE_TOUCH_COUNT = 4
MAX_DISPLAY_PER_SIDE = 3


def daily_context(s: MarketSnapshot) -> Direction:
    return structure_bias(s.xau_d1)


def build_candidates(s: MarketSnapshot) -> list[Candidate]:
    h4 = displacement_origins(s.xau_h4, "H4")
    h1 = displacement_origins(s.xau_h1, "H1")
    pad = max(0.01, 0.25 * (s.atr_h1 or atr(s.xau_h1)))
    out: list[Candidate] = []

    for direction in (Direction.BUY, Direction.SELL):
        parents = [x for x in h4 if x.direction == direction]
        children = [x for x in h1 if x.direction == direction]
        matched_h1: set[int] = set()

        for h in parents:
            matches = [x for x in children if _overlap(h.low, h.high, x.low, x.high, pad)]
            if matches:
                x = max(
                    matches,
                    key=lambda q: (
                        q.source_ts,
                        q.strength,
                        -abs((q.low + q.high - h.low - h.high) / 2.0),
                    ),
                )
                matched_h1.add(id(x))
                lo, hi, method = _cluster([h, x], x)
                out.append(
                    Candidate(
                        direction, lo, hi, "H4>H1", x.source_ts,
                        f"H4_PARENT_H1_REFINEMENT|{method}", [h, x]
                    )
                )
            else:
                out.append(
                    Candidate(
                        direction, h.low, h.high, "H4", h.source_ts,
                        "H4_PARENT_UNREFINED", [h]
                    )
                )

        for x in children:
            if id(x) in matched_h1:
                continue
            out.append(
                Candidate(
                    direction, x.low, x.high, "H1", x.source_ts,
                    "H1_INDEPENDENT_TACTICAL", [x]
                )
            )
    return out


def _distance_to_zone(mid: float, low: float, high: float) -> float:
    if low <= mid <= high:
        return 0.0
    if mid < low:
        return low - mid
    return mid - high


def _m15_refinement(c: Candidate, s: MarketSnapshot):
    m15a = s.atr_m15 or atr(s.xau_m15)
    pad = max(s.point * 5.0, 0.20 * m15a)
    matches = [
        x for x in displacement_origins(s.xau_m15, "M15", max_items=24)
        if x.direction == c.direction and _overlap(c.low, c.high, x.low, x.high, pad)
    ]
    if not matches:
        return None
    return max(matches, key=lambda x: (x.source_ts, x.strength, x.fvg))


def _readiness_from_method(method: str) -> str:
    return method.split("|", 1)[0] if "|" in method else "WATCH"


def _zone(c: Candidate, s: MarketSnapshot, liq, context: Direction, n: int) -> Zone:
    h1a = s.atr_h1 or atr(s.xau_h1)
    m15a = s.atr_m15 or atr(s.xau_m15)
    h4a = atr(s.xau_h4)

    core_low, core_high = c.low, c.high
    method = c.method
    source_ts = c.source_ts
    ref = _m15_refinement(c, s)
    if ref is not None:
        lo = max(c.low, ref.low)
        hi = min(c.high, ref.high)
        if lo <= hi:
            core_low, core_high = lo, hi
        else:
            core_low = max(min(ref.low, c.high), c.low)
            core_high = min(max(ref.high, c.low), c.high)
            if core_low >= core_high:
                core_low, core_high = c.low, c.high
        source_ts = max(source_ts, ref.source_ts)
        method = f"{method}|M15_REFINED"

    core_mid = (core_low + core_high) / 2.0
    loc = _location_score(c.direction, core_mid, s, liq)
    cap = max(1e-9, min(1.50 * h1a, 0.75 * h4a))
    zlo, zhi = core_low, core_high
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
    touches = _touches(zlo, zhi, source_ts, s.xau_m15)

    conf: list[str] = []
    if c.source_tf == "H4>H1":
        conf.append("H4_H1_OVERLAP")
    if c.source_tf in {"H4>H1", "H1"}:
        conf.append("H1_TACTICAL_EVIDENCE")
    if ref is not None:
        conf.append("M15_REFINEMENT")
    if any(x.fvg for x in c.components) or (ref is not None and ref.fvg):
        conf.append("HISTORICAL_DISPLACEMENT_FVG")
    if any(x.strength >= 2 for x in c.components) or (ref is not None and ref.strength >= 2):
        conf.append("INSTITUTIONAL_DISPLACEMENT")
    if loc >= 7:
        conf.append("PREMIUM_DISCOUNT_EXTREMITY")
    if notes and any(x.startswith("distal_liquidity:") for x in notes):
        conf.append("EXTERNAL_LIQUIDITY_ADJACENCY")
    if width_atr <= ACTIONABLE_MAX_M15_ATR:
        conf.append("M15_WIDTH_HEALTHY")
    if distance_h1_atr <= ACTIONABLE_MAX_H1_ATR:
        conf.append("INTRADAY_REACHABLE")

    original_targets = _targets(c.direction, core_mid, liq)
    flip = c.direction.opposite()
    flip_targets = _targets(flip, zhi if flip == Direction.BUY else zlo, liq)
    clear = abs(original_targets[0] - core_mid) if original_targets else 0.0
    counter = context not in (Direction.NEUTRAL, c.direction)
    need = SETTINGS.clear_run_countertrend if counter else SETTINGS.clear_run_with_trend

    retired = touches >= INTRADAY_RETIRE_TOUCH_COUNT
    too_remote = distance_h1_atr > CONTEXT_MAX_H1_ATR

    score = (
        (2 if c.source_tf == "H4>H1" else 1 if c.source_tf == "H1" else 0)
        + (2 if loc >= 8 else 1 if loc >= 6 else 0)
        + (1 if touches == 0 else 0)
        + (1 if "INSTITUTIONAL_DISPLACEMENT" in conf else 0)
        + (1 if ref is not None else 0)
        + (1 if distance_h1_atr <= PREFERRED_MAX_H1_ATR else 0)
        + (1 if width_atr <= ACTIONABLE_MAX_M15_ATR else 0)
        + (1 if clear >= need else 0)
    )
    grade = Grade.A_PLUS if score >= 8 else Grade.A if score >= 5 else Grade.B_PLUS

    actionable = (
        c.source_tf in {"H4>H1", "H1"}
        and ((grade == Grade.A_PLUS and touches <= 1) or (grade == Grade.A and touches <= 2))
        and distance_h1_atr <= ACTIONABLE_MAX_H1_ATR
        and width_atr <= ACTIONABLE_MAX_M15_ATR
        and clear >= need
        and len(set(conf)) >= SETTINGS.zone_min_independent_confluences
        and grade in (Grade.A_PLUS, Grade.A)
    )
    if actionable:
        readiness = "ACTIONABLE"
    elif distance_h1_atr <= WATCH_MAX_H1_ATR and width_atr <= WATCH_MAX_M15_ATR:
        readiness = "WATCH"
    else:
        readiness = "CONTEXT"

    if c.source_tf == "H4":
        readiness = "WATCH" if distance_h1_atr <= WATCH_MAX_H1_ATR else "CONTEXT"
        if grade in (Grade.A_PLUS, Grade.A):
            grade = Grade.B_PLUS
    if touches >= 3:
        readiness = "WATCH"
        grade = Grade.B_PLUS

    method = f"{readiness}|{method}"
    vals = original_targets + [0.0] * (4 - len(original_targets))
    fvals = flip_targets + [0.0] * (4 - len(flip_targets))
    inv = zhi if c.direction == Direction.SELL else zlo

    dxy = _dxy(s)
    support = (
        "NEUTRAL" if dxy == Direction.NEUTRAL
        else "SUPPORT"
        if ((c.direction == Direction.SELL and dxy == Direction.BUY)
            or (c.direction == Direction.BUY and dxy == Direction.SELL))
        else "CONFLICT"
    )

    notes = [
        f"readiness:{readiness}",
        "D1_CONTEXT_ONLY; H4 defines parent areas; H1 refines tactical location.",
        "M15 may refine the parent/tactical core and validates ATR/reachability/freshness.",
        "M1 execution OB/FVG/MSS triggers entry but cannot redefine the parent thesis.",
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
        grade=Grade.REJECT if (retired or too_remote) else grade,
        state=ZoneState.RETIRED if retired else ZoneState.ACTIVE,
        core_low=round(core_low, 5),
        core_high=round(core_high, 5),
        core_method=method,
        location_score=loc,
        zone_low=round(zlo, 5),
        zone_high=round(zhi, 5),
        touch_count=touches,
        confluences=sorted(set(conf)),
        independent_confluence_count=len(set(conf)),
        source_ts=source_ts,
        invalidation_level=round(inv, 5),
        invalidation_rule=(
            "M15 accepted body beyond OUTER envelope: one >=60% body and >=0.40 ATR, "
            "or two closes each >=0.20 ATR. Wick-only does not invalidate."
        ),
        original_target1=vals[0],
        original_target2=vals[1],
        original_target3=fvals[2] if False else vals[2],
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


def build_analysis(s: MarketSnapshot, generated_at: Optional[int] = None) -> Analysis:
    now = generated_at or int(datetime.now(timezone.utc).timestamp())
    liq = liquidity_map(s)
    context = daily_context(s)

    zones = [_zone(c, s, liq, context, i + 1) for i, c in enumerate(build_candidates(s))]
    zones = [z for z in zones if z.grade != Grade.REJECT and z.state != ZoneState.RETIRED]

    display: list[Zone] = []
    readiness_rank = {"ACTIONABLE": 0, "WATCH": 1, "CONTEXT": 2}
    h1a = max(s.atr_h1 or atr(s.xau_h1), 1e-9)
    for direction in (Direction.BUY, Direction.SELL):
        side = [z for z in zones if z.original_direction == direction]
        side.sort(
            key=lambda z: (
                readiness_rank.get(_readiness_from_method(z.core_method), 9),
                _distance_to_zone(s.mid, z.zone_low, z.zone_high) / h1a,
                GRADE_RANK[z.grade],
                TF_RANK.get(z.source_tf, 9),
                -z.location_score,
                z.touch_count,
            )
        )
        display.extend(side[:MAX_DISPLAY_PER_SIDE])

    for z in display:
        z.state = evaluate_zone_state(z, s.xau_m15, s.atr_m15)

    selected = ""
    executable = [
        z for z in display
        if _readiness_from_method(z.core_method) == "ACTIONABLE"
        and z.grade in (Grade.A_PLUS, Grade.A)
        and z.state == ZoneState.ACTIVE
    ]
    if executable:
        executable.sort(
            key=lambda z: (
                _distance_to_zone(s.mid, z.zone_low, z.zone_high) / h1a,
                GRADE_RANK[z.grade],
                -z.location_score,
            )
        )
        selected = executable[0].zone_id

    above = sorted([x for x in liq if x.side == "ABOVE"], key=lambda x: x.distance)
    below = sorted([x for x in liq if x.side == "BELOW"], key=lambda x: x.distance)
    primary = (
        above[0] if context == Direction.BUY and above
        else below[0] if context == Direction.SELL and below
        else sorted(liq, key=lambda x: x.distance)[0] if liq
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

    counts = {"ACTIONABLE": 0, "WATCH": 0, "CONTEXT": 0}
    for z in display:
        r = _readiness_from_method(z.core_method)
        if r in counts:
            counts[r] += 1

    return Analysis(
        analysis_id=f"A_{now}_{uuid.uuid4().hex[:8]}",
        generated_at=now,
        snapshot_at=s.sent_at,
        overall_bias=context,
        primary_liquidity=f"{primary.label}@{primary.price:.5f}" if primary else "",
        liquidity_map=liq,
        zones=display,
        selected_zone_id=selected,
        trader_brief=(
            f"D1 context={context.value}. H4 parent -> H1 tactical -> M15 refinement/health; "
            f"M1 execution unchanged. DXY={_dxy(s).value} analysis-only. "
            f"Zones: {counts['ACTIONABLE']} actionable, {counts['WATCH']} watch, "
            f"{counts['CONTEXT']} context."
        ),
        approved=not hard_block,
        execution_policy={
            "core": "D1_CONTEXT_H4_PARENT_H1_TACTICAL_M15_REFINEMENT_HEALTH",
            "zone_states": ["ACTIONABLE", "WATCH", "CONTEXT"],
            "primary": [
                "D1_CONTEXT",
                "H4_PARENT_LOCATION",
                "H1_TACTICAL_REFINEMENT",
                "M15_REFINEMENT_ATR_REACHABILITY_FRESHNESS",
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
