from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import SETTINGS
from .engine import (
    _location_score,
    _targets,
    _touches,
    atr,
    displacement_origins,
    evaluate_zone_state,
    structure_bias,
)
from .models import Analysis, Bar, Direction, Grade, MarketSnapshot, Zone, ZoneState
from .mitigation_audit import audit_directional_mitigations
from .prompt_contract import prompt_dxy_direction
from .thesis_ownership_policy import active_owner_snapshot
from .zone_runtime_policy import MIN_SWEEP_ROOM_POINTS, XAU_POINTS_PER_PIP, _geometry_points

DYNAMIC_CONTINUATION_CONTRACT = "DYNAMIC_CONTINUATION_REZONE_V6521"
MAX_H1_EVENT_AGE_BARS = 8
MAX_H4_EVENT_AGE_BARS = 3
REPLACE_ADVANTAGE_H1_ATR = 0.35
COUNTERTREND_DEMOTE_TOUCHES = 3
STRONG_EVENT_MIN_STRENGTH = 1.80
STRONG_EVENT_MAX_AGE_BARS = 3

TF_SECONDS = {"H1": 3600, "H4": 14400}


@dataclass(frozen=True)
class ContinuationEvent:
    direction: Direction
    source_tf: str
    source_ts: int
    displacement_ts: int
    strength: float
    fvg_low: float
    fvg_high: float
    age_bars: int


def _event_ready_ts(event: ContinuationEvent) -> int:
    return int(event.displacement_ts) + int(TF_SECONDS.get(str(event.source_tf).upper(), 0))


def _point(snapshot: MarketSnapshot) -> float:
    return max(abs(float(snapshot.point or 0.01)), 1e-9)


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _fvg_bounds(bars: list[Bar], index: int, direction: Direction) -> tuple[float, float] | None:
    if index < 1 or index + 1 >= len(bars):
        return None
    left = bars[index - 1]
    right = bars[index + 1]
    if direction == Direction.SELL:
        low, high = float(right.high), float(left.low)
    else:
        low, high = float(left.high), float(right.low)
    if high <= low:
        return None
    return low, high


def _recent_events(snapshot: MarketSnapshot, direction: Direction) -> list[ContinuationEvent]:
    out: list[ContinuationEvent] = []
    for tf, bars, max_age in (
        ("H1", list(snapshot.xau_h1), MAX_H1_EVENT_AGE_BARS),
        ("H4", list(snapshot.xau_h4), MAX_H4_EVENT_AGE_BARS),
    ):
        if len(bars) < 30:
            continue
        for origin in displacement_origins(bars, tf, max_items=18):
            if origin.direction != direction or not bool(origin.fvg):
                continue
            i = int(origin.displacement_index)
            bounds = _fvg_bounds(bars, i, direction)
            if bounds is None:
                continue
            age = (len(bars) - 1) - i
            if age < 0 or age > max_age:
                continue
            fvg_low, fvg_high = bounds
            # A continuation retest must remain on the retracement side of current
            # delivery. If price has already accepted completely through the FVG,
            # it is no longer a fresh continuation location.
            if direction == Direction.SELL and float(snapshot.mid) > fvg_high:
                continue
            if direction == Direction.BUY and float(snapshot.mid) < fvg_low:
                continue
            out.append(
                ContinuationEvent(
                    direction=direction,
                    source_tf=tf,
                    source_ts=int(origin.source_ts),
                    displacement_ts=int(bars[i].ts),
                    strength=float(origin.strength),
                    fvg_low=float(fvg_low),
                    fvg_high=float(fvg_high),
                    age_bars=int(age),
                )
            )
    out.sort(
        key=lambda e: (
            _distance(float(snapshot.mid), e.fvg_low, e.fvg_high),
            0 if e.source_tf == "H1" else 1,
            e.age_bars,
            -e.strength,
            -e.displacement_ts,
        )
    )
    return out


def _required_liquidity(direction: Direction) -> str:
    return "BSL" if direction == Direction.SELL else "SSL"


def _select_liquidity(event: ContinuationEvent, analysis: Analysis, snapshot: MarketSnapshot):
    required = _required_liquidity(event.direction)
    point = _point(snapshot)
    contract = _geometry_points(event.source_tf)
    max_core_span = float(contract["core_max"]) * point
    fvg_mid = (event.fvg_low + event.fvg_high) / 2.0
    tf_rank = {"H1": 0, "H4": 1, "D1": 2}
    options = []
    for level in analysis.liquidity_map:
        if required not in str(level.label).upper():
            continue
        tf = str(level.source_tf).upper()
        if tf not in {"H1", "H4", "D1"}:
            continue
        price = float(level.price)
        # The structural liquidity must be close enough to the displacement FVG
        # that both can participate in one professional tactical core. This keeps
        # FVG/OB information as confluence, not a standalone zone factory.
        span = max(event.fvg_high, price) - min(event.fvg_low, price)
        if span > max_core_span + 1e-9:
            continue
        options.append((tf_rank.get(tf, 9), abs(price - fvg_mid), float(level.distance), level))
    if not options:
        return None
    options.sort(key=lambda row: row[:-1])
    return options[0][-1]


def _liquidity_centered_geometry(event: ContinuationEvent, liquidity_price: float, snapshot: MarketSnapshot):
    point = _point(snapshot)
    contract = _geometry_points(event.source_tf)
    fvg_width_points = max(0.0, event.fvg_high - event.fvg_low) / point
    core_width_points = min(
        max(float(contract["core_min"]), fvg_width_points),
        float(contract["core_max"]),
    )
    half_core = 0.5 * core_width_points * point
    core_low = liquidity_price - half_core
    core_high = liquidity_price + half_core
    if event.fvg_high < core_low or event.fvg_low > core_high:
        return None

    sweep = MIN_SWEEP_ROOM_POINTS * point
    low = min(core_low, event.fvg_low, liquidity_price - sweep)
    high = max(core_high, event.fvg_high, liquidity_price + sweep)
    width = high - low
    min_width = float(contract["envelope_min"]) * point
    max_width = float(contract["envelope_max"]) * point
    if width < min_width:
        half = 0.5 * min_width
        low = min(low, liquidity_price - half)
        high = max(high, liquidity_price + half)
        width = high - low
    if width > max_width + 1e-9:
        return None

    # Preserve at least the V659 50-pip sweep reserve on the distal side while
    # also keeping a meaningful buffer on the opposite side of the core liquidity.
    if liquidity_price - low < sweep - 1e-9 or high - liquidity_price < sweep - 1e-9:
        return None
    return core_low, core_high, low, high


def _dxy_support(direction: Direction, snapshot: MarketSnapshot) -> str:
    dxy = prompt_dxy_direction(snapshot)
    if dxy == Direction.NEUTRAL:
        return "NEUTRAL"
    if (direction == Direction.SELL and dxy == Direction.BUY) or (
        direction == Direction.BUY and dxy == Direction.SELL
    ):
        return "SUPPORT"
    return "CONFLICT"


def _build_dynamic_zone(event: ContinuationEvent, analysis: Analysis, snapshot: MarketSnapshot) -> Zone | None:
    attached = _select_liquidity(event, analysis, snapshot)
    if attached is None:
        return None
    liquidity_price = float(attached.price)
    geometry = _liquidity_centered_geometry(event, liquidity_price, snapshot)
    if geometry is None:
        return None
    core_low, core_high, zone_low, zone_high = geometry
    mitigation_start_ts = _event_ready_ts(event)
    raw_touch_episodes = _touches(core_low, core_high, mitigation_start_ts, snapshot.xau_m15)
    mitigation_audit = audit_directional_mitigations(
        event.direction,
        core_low,
        core_high,
        zone_low,
        zone_high,
        mitigation_start_ts,
        snapshot.xau_m15,
    )
    if not bool(mitigation_audit.get("history_complete")):
        return None
    if int(mitigation_audit.get("invalidated_at") or 0) > 0:
        return None
    touches = int(mitigation_audit.get("qualified_mitigations") or 0)
    if touches > 1:
        return None

    core_mid = (core_low + core_high) / 2.0
    loc = _location_score(event.direction, core_mid, snapshot, analysis.liquidity_map)
    h1_aligned = structure_bias(snapshot.xau_h1) == event.direction
    h4_aligned = structure_bias(snapshot.xau_h4) == event.direction
    grade = Grade.A_PLUS if event.source_tf == "H4" and h1_aligned and event.strength >= 2.0 else Grade.A
    required = _required_liquidity(event.direction)
    confluences = {
        "DYNAMIC_CONTINUATION_REZONE",
        "INSTITUTIONAL_DISPLACEMENT",
        "HISTORICAL_DISPLACEMENT_FVG",
        "FRESH_DISPLACEMENT_RETEST",
        "LIQUIDITY_IN_MARKED_ZONE",
        f"{required}_IN_MARKED_ZONE",
        "LIQUIDITY_CENTERED_CORE",
        "BALANCED_CORE_BUFFER",
        "PROFESSIONAL_SOURCE_TF_CORE_WIDTH",
        "PROFESSIONAL_SOURCE_TF_ENVELOPE_WIDTH",
        "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM",
        "SWEEP_ROOM_RESERVED",
    }
    if h1_aligned:
        confluences.add("H1_TREND_ALIGNED")
    if h4_aligned:
        confluences.add("H4_TREND_ALIGNED")
    if loc >= 7.0:
        confluences.add("PREMIUM_DISCOUNT_EXTREMITY")

    original = _targets(event.direction, core_mid, analysis.liquidity_map)
    flip = event.direction.opposite()
    flip_ref = zone_high if flip == Direction.BUY else zone_low
    flipped = _targets(flip, flip_ref, analysis.liquidity_map)
    vals = original + [0.0] * (4 - len(original))
    fvals = flipped + [0.0] * (4 - len(flipped))
    clear_run = abs(float(vals[0]) - core_mid) if vals and vals[0] else 0.0
    point = _point(snapshot)
    sweep_points = (
        (zone_high - liquidity_price) / point
        if event.direction == Direction.SELL
        else (liquidity_price - zone_low) / point
    )

    zone = Zone(
        zone_id=f"DC_{event.source_tf}_{event.direction.value}_{event.displacement_ts}",
        original_direction=event.direction,
        flip_direction=flip,
        setup_type="CONTINUATION",
        source_tf=event.source_tf,
        grade=grade,
        state=ZoneState.ACTIVE,
        core_low=round(core_low, 5),
        core_high=round(core_high, 5),
        core_method="ARMED|DYNAMIC_CONTINUATION_REZONE|FVG_BOS_LIQUIDITY_CENTERED",
        location_score=round(loc, 4),
        zone_low=round(zone_low, 5),
        zone_high=round(zone_high, 5),
        touch_count=int(touches),
        mitigation_audit=mitigation_audit,
        confluences=sorted(confluences),
        independent_confluence_count=len(confluences),
        requires_sweep=True,
        source_ts=int(event.displacement_ts),
        invalidation_level=round(zone_high if event.direction == Direction.SELL else zone_low, 5),
        invalidation_rule="Closed M15 body acceptance beyond the dynamic continuation outer envelope invalidates the retest. Wick-only liquidity raids do not invalidate.",
        original_target1=float(vals[0]),
        original_target2=float(vals[1]),
        original_target3=float(vals[2]),
        original_runner=float(vals[3]),
        flip_target1=float(fvals[0]),
        flip_target2=float(fvals[1]),
        flip_target3=float(fvals[2]),
        flip_runner=float(fvals[3]),
        clear_run=round(clear_run, 5),
        countertrend=False,
        dxy_support=_dxy_support(event.direction, snapshot),
        notes=[
            "readiness:ARMED",
            f"dynamic_continuation_contract:{DYNAMIC_CONTINUATION_CONTRACT}",
            f"displacement_source:{event.source_tf}:{event.displacement_ts}",
            f"source_ready_ts:{mitigation_start_ts}",
            f"parent_ob_source_ts:{event.source_ts}",
            f"fvg:{event.fvg_low:.5f}-{event.fvg_high:.5f}",
            f"attached_liquidity:{required}:{attached.label}@{liquidity_price:.5f}",
            f"core_width_points:{(core_high-core_low)/point:.1f}",
            f"envelope_width_points:{(zone_high-zone_low)/point:.1f}",
            f"sweep_room_points:{sweep_points:.1f}",
            f"mitigations:{touches}",
            f"raw_core_touch_episodes:{raw_touch_episodes}",
            "Mitigation freshness is directional: SELL below->core->below; BUY above->core->above. Wrong-side contacts do not count.",
            "The FVG is not a standalone zone. A recent BOS displacement plus nearby structural liquidity is mandatory.",
            "The structural liquidity sits inside a balanced tactical core with buffer on both sides; M1 confirmation remains mandatory.",
        ],
    )
    if evaluate_zone_state(zone, snapshot.xau_m15, snapshot.atr_m15) != ZoneState.ACTIVE:
        return None
    return zone


def _expansion_state(snapshot: MarketSnapshot, context: Direction, events: list[ContinuationEvent]) -> dict[str, Any]:
    h1 = structure_bias(snapshot.xau_h1)
    h4 = structure_bias(snapshot.xau_h4)
    strong_recent_event = any(
        e.source_tf == "H1"
        and e.age_bars <= STRONG_EVENT_MAX_AGE_BARS
        and e.strength >= STRONG_EVENT_MIN_STRENGTH
        for e in events
    )
    aligned = bool(
        context in {Direction.BUY, Direction.SELL}
        and events
        and (h1 == context or h4 == context or strong_recent_event)
    )
    return {
        "aligned": aligned,
        "d1": context.value,
        "h1": h1.value,
        "h4": h4.value,
        "recent_event_count": len(events),
        "strong_recent_h1_displacement": strong_recent_event,
    }


def _zone_payload(zone: Zone) -> dict[str, Any]:
    return {
        "zone_id": zone.zone_id,
        "direction": zone.original_direction.value,
        "source_tf": zone.source_tf,
        "grade": zone.grade.value,
        "state": zone.state.value,
        "core_low": zone.core_low,
        "core_high": zone.core_high,
        "low": zone.zone_low,
        "high": zone.zone_high,
        "touches": zone.touch_count,
        "source_ts": zone.source_ts,
    }


def _sync_public_map(analysis: Analysis) -> None:
    policy = dict(analysis.execution_policy or {})
    zone_map = dict(policy.get("public_zone_map") or {})
    zone_map.pop("sell", None)
    zone_map.pop("buy", None)
    for zone in analysis.zones:
        side = zone.original_direction.value.lower()
        zone_map[side] = {
            "state": str(zone.core_method or "").split("|", 1)[0],
            "source_tf": zone.source_tf,
            "grade": zone.grade.value,
            "low": zone.zone_low,
            "high": zone.zone_high,
            "core_low": zone.core_low,
            "core_high": zone.core_high,
            "touches": zone.touch_count,
            "qualified_mitigations": zone.touch_count,
            "mitigation_audit": dict(zone.mitigation_audit or {}),
            "mitigation_expected_approach_side": str((zone.mitigation_audit or {}).get("expected_approach_side") or ""),
            "mitigation_counting_stopped": bool((zone.mitigation_audit or {}).get("counting_stopped")),
            "source_ts": zone.source_ts,
            "dynamic_continuation": "DYNAMIC_CONTINUATION_REZONE" in set(zone.confluences),
        }
    zone_map["map_count"] = len(analysis.zones)
    policy["public_zone_map"] = zone_map
    analysis.execution_policy = policy


def apply_dynamic_continuation_rezone(analysis: Analysis, snapshot: MarketSnapshot) -> Analysis:
    """Re-rank fresh trend-continuation locations after a strong displacement leg.

    Historical countertrend demand/supply remains lifecycle truth, but only an exhausted
    three-plus-touch countertrend zone is removed from the *execution map* during a
    confirmed same-direction expansion. A nearer continuation FVG can replace a
    remote primary only when it comes from a recent BOS displacement and has nearby
    structural BSL/SSL inside a V659 liquidity-centered core. This function never
    sends orders and never bypasses M1 confirmation.
    """
    if analysis is None or not SETTINGS.paper_only:
        return analysis
    context = analysis.overall_bias
    if context not in {Direction.BUY, Direction.SELL}:
        return analysis

    owner = active_owner_snapshot(int(snapshot.sent_at))
    events = _recent_events(snapshot, context)
    expansion = _expansion_state(snapshot, context, events)
    policy = dict(analysis.execution_policy or {})
    audit_meta: dict[str, Any] = {
        "contract": DYNAMIC_CONTINUATION_CONTRACT,
        "paper_only": True,
        "expansion": expansion,
        "owner_protected": bool(owner),
        "fvg_alone_can_create_zone": False,
        "structural_liquidity_required": True,
        "liquidity_centered_core": True,
        "professional_v659_geometry": True,
        "minimum_distal_sweep_room_pips": MIN_SWEEP_ROOM_POINTS / XAU_POINTS_PER_PIP,
        "m1_confirmation_required": True,
        "demoted_context_zones": [],
        "replaced_primary": None,
        "dynamic_primary": None,
    }
    policy["dynamic_continuation_rezone"] = audit_meta
    analysis.execution_policy = policy

    if owner is not None:
        analysis.trader_brief += " Dynamic continuation re-zoning held because an already-acquired thesis owns execution."
        return analysis
    if not expansion["aligned"]:
        return analysis

    # Demote only genuinely exhausted countertrend locations. A structurally valid B+
    # second-touch zone remains eligible for reduced-risk research execution; trend
    # alignment alone does not prove that the opposing HTF source is invalid.
    kept: list[Zone] = []
    for zone in analysis.zones:
        exhausted_countertrend = bool(
            zone.original_direction != context
            and int(zone.touch_count) >= COUNTERTREND_DEMOTE_TOUCHES
        )
        if exhausted_countertrend:
            audit_meta["demoted_context_zones"].append(
                {
                    **_zone_payload(zone),
                    "reason": "COUNTERTREND_EXHAUSTED_THREE_PLUS_TOUCHES_DURING_ALIGNED_EXPANSION",
                    "execution_authority": False,
                }
            )
            if analysis.selected_zone_id == zone.zone_id:
                analysis.selected_zone_id = ""
            continue
        kept.append(zone)
    analysis.zones = kept

    dynamic_candidates = [
        zone
        for event in events
        if (zone := _build_dynamic_zone(event, analysis, snapshot)) is not None
    ]
    if dynamic_candidates:
        dynamic_candidates.sort(
            key=lambda z: (
                _distance(float(snapshot.mid), float(z.core_low), float(z.core_high)),
                int(z.touch_count),
                0 if z.grade == Grade.A_PLUS else 1,
                -int(z.source_ts),
            )
        )
        dynamic = dynamic_candidates[0]
        same = next((z for z in analysis.zones if z.original_direction == context), None)
        h1a = max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), _point(snapshot))
        dynamic_distance = _distance(float(snapshot.mid), dynamic.core_low, dynamic.core_high)
        replace = same is None
        if same is not None:
            same_readiness = str(same.core_method or "").split("|", 1)[0]
            same_distance = _distance(float(snapshot.mid), same.core_low, same.core_high)
            replace = bool(
                same_readiness not in {"INTERACTING", "M1_READY"}
                and dynamic_distance + REPLACE_ADVANTAGE_H1_ATR * h1a < same_distance
            )
        if replace:
            if same is not None:
                analysis.zones = [z for z in analysis.zones if z.zone_id != same.zone_id]
                audit_meta["replaced_primary"] = {
                    **_zone_payload(same),
                    "reason": "FRESH_NEARER_DISPLACEMENT_RETEST",
                }
            analysis.zones.append(dynamic)
            audit_meta["dynamic_primary"] = _zone_payload(dynamic)

    # Keep context-direction zone first, then any still-valid opposing reversal zone.
    analysis.zones.sort(key=lambda z: (0 if z.original_direction == context else 1, z.zone_low))
    context_zone = next(
        (
            z
            for z in analysis.zones
            if z.original_direction == context
            and z.grade in {Grade.A_PLUS, Grade.A, Grade.B_PLUS}
            and z.state == ZoneState.ACTIVE
        ),
        None,
    )
    if context_zone is not None:
        analysis.selected_zone_id = context_zone.zone_id
    elif analysis.selected_zone_id and not any(z.zone_id == analysis.selected_zone_id for z in analysis.zones):
        analysis.selected_zone_id = ""

    policy = dict(analysis.execution_policy or {})
    policy["dynamic_continuation_rezone"] = audit_meta
    analysis.execution_policy = policy
    _sync_public_map(analysis)

    if audit_meta["demoted_context_zones"]:
        sides = ",".join(str(x.get("zone_id")) for x in audit_meta["demoted_context_zones"])
        analysis.trader_brief += (
            f" Dynamic continuation context: {sides} demoted from the execution map because it is countertrend and exhausted; historical lifecycle remains preserved."
        )
    if audit_meta["dynamic_primary"]:
        z = audit_meta["dynamic_primary"]
        analysis.trader_brief += (
            f" Dynamic continuation re-zone={z['direction']} {z['low']:.2f}-{z['high']:.2f} "
            f"(core={z['core_low']:.2f}-{z['core_high']:.2f},{z['source_tf']},{z['grade']}). "
            "It is a fresh displacement/FVG retest with structural liquidity centered in the core; FVG alone has no zone authority."
        )

    active_map = "; ".join(
        f"{z.original_direction.value}={z.zone_low:.2f}-{z.zone_high:.2f} (core={z.core_low:.2f}-{z.core_high:.2f},{z.source_tf},{z.grade.value})"
        for z in analysis.zones
    ) or "none"
    analysis.trader_brief += f" Active execution map after continuation re-ranking: {active_map}."
    return analysis
