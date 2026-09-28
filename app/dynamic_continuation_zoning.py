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

DYNAMIC_CONTINUATION_CONTRACT = "MASTER_SNIPER_SOURCE_EXACT_CONTINUATION_V6594"
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
    # Dynamic continuation requires a three-candle FVG around the displacement.
    # The array is not causally known until the newer third candle closes.
    tf_seconds = int(TF_SECONDS.get(str(event.source_tf).upper(), 0))
    return int(event.displacement_ts) + 2 * tf_seconds


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


def _source_bar(event: ContinuationEvent, snapshot: MarketSnapshot) -> Bar | None:
    bars = snapshot.xau_h1 if event.source_tf == "H1" else snapshot.xau_h4 if event.source_tf == "H4" else []
    return next((bar for bar in bars if int(bar.ts) == int(event.source_ts)), None)


def _build_dynamic_zone(event: ContinuationEvent, analysis: Analysis, snapshot: MarketSnapshot) -> Zone | None:
    """Build a fresh continuation zone from the *actual* H1/H4 source candle.

    The old FVG-centred synthetic geometry is intentionally not used. The recent
    BOS/FVG event is only a discovery trigger. Final qualification is delegated
    back to the installed Master Sniper source-exact candidate path, which still
    requires genuine BSL/SSL inside the source envelope, closed evidence,
    directional mitigation health and normal grade rules.
    """
    from . import institutional_two_zone as zoning

    source = _source_bar(event, snapshot)
    if source is None:
        return None
    body_low, body_high = sorted((float(source.open), float(source.close)))
    if body_high <= body_low:
        body_low, body_high = float(source.low), float(source.high)

    candidate = zoning.PromptCandidate(
        direction=event.direction,
        source_tf=event.source_tf,
        source_ts=int(event.source_ts),
        core_low=float(body_low),
        core_high=float(body_high),
        zone_low=float(source.low),
        zone_high=float(source.high),
        strength=float(event.strength),
        fvg=True,
        source_kind="DISPLACEMENT_BOS_SOURCE",
        volume_expansion=bool(zoning._volume_expansion(
            snapshot.xau_h1 if event.source_tf == "H1" else snapshot.xau_h4,
            int(event.source_ts),
        )),
        method="PROMPT_H1_TACTICAL_SOURCE" if event.source_tf == "H1" else "PROMPT_H4_SOURCE_CANDLE",
        source_ready_ts=_event_ready_ts(event),
    )
    zone, _diag = zoning._candidate_zone(
        candidate,
        snapshot,
        analysis.liquidity_map,
        analysis.overall_bias,
        0,
    )
    if zone is None:
        return None

    readiness = str(zone.core_method or "").split("|", 1)[0]
    tail = str(zone.core_method or "").split("|", 1)[1] if "|" in str(zone.core_method or "") else ""
    zone.core_method = (
        f"{readiness}|MASTER_SNIPER_SOURCE_EXACT_CONTINUATION|{tail}"
        if tail else
        f"{readiness}|MASTER_SNIPER_SOURCE_EXACT_CONTINUATION"
    )
    conf = set(zone.confluences or [])
    conf.update({
        "DYNAMIC_CONTINUATION_SOURCE_EXACT",
        "FRESH_DISPLACEMENT_RETEST",
        "NO_SYNTHETIC_ZONE_EXPANSION",
    })
    zone.confluences = sorted(conf)
    zone.independent_confluence_count = len(zone.confluences)
    zone.notes = list(zone.notes or []) + [
        f"dynamic_continuation_contract:{DYNAMIC_CONTINUATION_CONTRACT}",
        f"displacement_source:{event.source_tf}:{event.displacement_ts}",
        f"fvg:{event.fvg_low:.5f}-{event.fvg_high:.5f}",
        "Fresh continuation discovery used the recent BOS/FVG only as evidence. The published core/envelope remain the actual H1/H4 source candle with attached structural liquidity.",
    ]
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
    """Synchronize the execution map without destroying grade/publication audit truth.

    The base prompt engine already publishes structural/current grade metadata,
    freshness diagnostics and source-quality gaps. Continuation re-ranking may
    remove or replace a side, but a surviving zone must retain those fields.
    """
    policy = dict(analysis.execution_policy or {})
    zone_map = dict(policy.get("public_zone_map") or {})
    previous_by_side = {
        "sell": dict(zone_map.get("sell") or {}),
        "buy": dict(zone_map.get("buy") or {}),
    }
    zone_map.pop("sell", None)
    zone_map.pop("buy", None)

    def note_text(zone: Zone, prefix: str, fallback: str = "") -> str:
        for raw in list(zone.notes or []):
            text = str(raw)
            if text.startswith(prefix):
                return text.split(":", 1)[1]
        return fallback

    def note_float(zone: Zone, prefix: str, fallback: float = 0.0) -> float:
        raw = note_text(zone, prefix, "")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(fallback)

    for zone in analysis.zones:
        side = zone.original_direction.value.lower()
        previous = previous_by_side.get(side) or {}
        same_zone = str(previous.get("zone_id") or previous.get("audit_zone_id") or "") == str(zone.zone_id)
        preserved = previous if same_zone else {}

        structural_grade = note_text(
            zone,
            "structural_grade:",
            str(preserved.get("structural_grade") or zone.grade.value),
        )
        current_grade = note_text(zone, "current_execution_grade:", zone.grade.value)
        grade_reason = note_text(
            zone,
            "grade_degrade_reason:",
            str(preserved.get("grade_degrade_reason") or "NONE"),
        )
        aplus_gap = note_text(
            zone,
            "structural_aplus_missing:",
            str(preserved.get("structural_aplus_missing") or "NONE"),
        )
        a_gap = note_text(
            zone,
            "structural_a_missing:",
            str(preserved.get("structural_a_missing") or "NONE"),
        )

        zone_map[side] = {
            **preserved,
            "zone_id": zone.zone_id,
            "state": str(zone.core_method or "").split("|", 1)[0],
            "source_tf": zone.source_tf,
            "structural_grade": structural_grade,
            "grade": current_grade,
            "current_execution_grade": current_grade,
            "grade_degrade_reason": grade_reason,
            "structural_aplus_missing": aplus_gap,
            "structural_a_missing": a_gap,
            "grade_location_score": note_float(
                zone,
                "grade_location_score:",
                float(preserved.get("grade_location_score") or zone.location_score or 0.0),
            ),
            "grade_source_strength": note_float(
                zone,
                "grade_source_strength:",
                float(preserved.get("grade_source_strength") or 0.0),
            ),
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
            "dynamic_continuation": bool(
                {"DYNAMIC_CONTINUATION_REZONE", "DYNAMIC_CONTINUATION_SOURCE_EXACT"}
                & set(zone.confluences)
            ),
        }
    zone_map["map_count"] = len(analysis.zones)
    policy["public_zone_map"] = zone_map
    analysis.execution_policy = policy


def _continuation_context(analysis: Analysis, snapshot: MarketSnapshot) -> tuple[Direction, list[ContinuationEvent], dict[str, Any]]:
    """Resolve continuation direction without letting neutral D1 suppress H1/H4 delivery."""
    d1_context = analysis.overall_bias
    directions = (
        [d1_context]
        if d1_context in {Direction.BUY, Direction.SELL}
        else [Direction.SELL, Direction.BUY]
    )
    qualified: list[tuple[Direction, list[ContinuationEvent], dict[str, Any]]] = []
    for direction in directions:
        events = _recent_events(snapshot, direction)
        expansion = _expansion_state(snapshot, direction, events)
        if expansion.get("aligned"):
            qualified.append((direction, events, expansion))
    if not qualified:
        return Direction.NEUTRAL, [], {
            "aligned": False,
            "d1": d1_context.value,
            "h1": structure_bias(snapshot.xau_h1).value,
            "h4": structure_bias(snapshot.xau_h4).value,
            "recent_event_count": 0,
            "strong_recent_h1_displacement": False,
        }
    qualified.sort(
        key=lambda item: (
            -max((int(e.displacement_ts) for e in item[1]), default=0),
            -max((float(e.strength) for e in item[1]), default=0.0),
            0 if structure_bias(snapshot.xau_h1) == item[0] else 1,
            0 if structure_bias(snapshot.xau_h4) == item[0] else 1,
        )
    )
    direction, events, expansion = qualified[0]
    expansion = {**expansion, "d1": d1_context.value, "continuation_direction": direction.value}
    return direction, events, expansion


def apply_dynamic_continuation_rezone(analysis: Analysis, snapshot: MarketSnapshot) -> Analysis:
    """Re-rank fresh trend-continuation locations after a strong displacement leg.

    A recent BOS/FVG event may cause the map to inspect its actual H1/H4 source
    candle. A nearer continuation may replace a remote same-direction primary only
    when that real source candle independently passes the normal Master Sniper
    source/liquidity/M15 qualification. FVG is confluence only; no synthetic
    liquidity-centred geometry is permitted. This function never sends orders and
    never bypasses M1 confirmation.
    """
    if analysis is None or not SETTINGS.paper_only:
        return analysis
    context, events, expansion = _continuation_context(analysis, snapshot)
    owner = active_owner_snapshot(int(snapshot.sent_at))
    policy = dict(analysis.execution_policy or {})
    audit_meta: dict[str, Any] = {
        "contract": DYNAMIC_CONTINUATION_CONTRACT,
        "paper_only": True,
        "expansion": expansion,
        "owner_protected": bool(owner),
        "fvg_alone_can_create_zone": False,
        "structural_liquidity_required": True,
        "source_exact_geometry": True,
        "synthetic_fvg_centered_geometry": False,
        "d1_neutral_can_use_confirmed_h1_h4_expansion": True,
        "continuation_direction": context.value,
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
    if context not in {Direction.BUY, Direction.SELL} or not expansion["aligned"]:
        return analysis

    # Immutable-grade contract: mitigation/touch history is telemetry only.
    # Aligned expansion may discover a fresh continuation source, but it must never
    # demote or delete an opposing valid zone merely because of prior touches.
    audit_meta["touch_count_can_demote_zone"] = False

    dynamic_candidates = [
        zone
        for event in events
        if (zone := _build_dynamic_zone(event, analysis, snapshot)) is not None
    ]
    if dynamic_candidates:
        dynamic_candidates.sort(
            key=lambda z: (
                _distance(float(snapshot.mid), float(z.core_low), float(z.core_high)),
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
            f" Dynamic continuation context: {sides} recorded as telemetry only; touch count cannot demote a valid zone."
        )
    if audit_meta["dynamic_primary"]:
        z = audit_meta["dynamic_primary"]
        analysis.trader_brief += (
            f" Dynamic continuation re-zone={z['direction']} {z['low']:.2f}-{z['high']:.2f} "
            f"(core={z['core_low']:.2f}-{z['core_high']:.2f},{z['source_tf']},{z['grade']}). "
            "It is a fresh source-exact H1/H4 displacement retest with genuine attached structural liquidity; FVG is confluence only and cannot manufacture geometry."
        )

    active_map = "; ".join(
        f"{z.original_direction.value}={z.zone_low:.2f}-{z.zone_high:.2f} (core={z.core_low:.2f}-{z.core_high:.2f},{z.source_tf},{z.grade.value})"
        for z in analysis.zones
    ) or "none"
    analysis.trader_brief += f" Active execution map after continuation re-ranking: {active_map}."
    return analysis
