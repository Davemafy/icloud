from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import statistics
import uuid

from .config import SETTINGS
from .engine import (
    _location_score,
    _targets,
    _touches,
    atr,
    displacement_origins,
    evaluate_zone_state,
    liquidity_map,
    structure_bias,
)
from .models import Analysis, Bar, Direction, Grade, MarketSnapshot, Zone, ZoneState
from .mitigation_audit import audit_directional_mitigations
from .prompt_contract import prompt_dxy_direction, prompt_snapshot_complete
from .risk_matrix import execution_grade_eligible

SWEEP_LOOKBACK = 8
FOLLOW_THROUGH_BARS = 3
MIN_REJECTION_WICK_FRACTION = 0.30
MIN_FOLLOW_THROUGH_ATR = 0.60
H1_PARENT_OVERLAP_ATR = 0.25
APPROACH_BUFFER_M15_ATR = 0.30
CORE_MIN_POINTS = 100.0
CORE_MAX_POINTS = 150.0
ENVELOPE_MIN_POINTS = 200.0
ENVELOPE_MAX_POINTS = 300.0
MIN_SWEEP_ROOM_POINTS = 50.0


@dataclass
class PromptSource:
    direction: Direction
    tf: str
    source_ts: int
    core_low: float
    core_high: float
    zone_low: float
    zone_high: float
    strength: float
    fvg: bool
    source_kind: str
    volume_expansion: bool


@dataclass
class PromptCandidate:
    direction: Direction
    source_tf: str
    source_ts: int
    core_low: float
    core_high: float
    zone_low: float
    zone_high: float
    strength: float
    fvg: bool
    source_kind: str
    volume_expansion: bool
    method: str


def _point(snapshot: MarketSnapshot) -> float:
    return max(abs(float(snapshot.point or 0.01)), 1e-9)


def _to_points(distance: float, snapshot: MarketSnapshot) -> float:
    return float(distance) / _point(snapshot)


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _bar_by_ts(bars: list[Bar], ts: int) -> Bar | None:
    return next((b for b in bars if int(b.ts) == int(ts)), None)


def _volume_expansion(bars: list[Bar], ts: int) -> bool:
    idx = next((i for i, b in enumerate(bars) if int(b.ts) == int(ts)), None)
    if idx is None or idx <= 0:
        return False
    prior = [float(x.tick_volume or 0.0) for x in bars[max(0, idx - 20):idx] if float(x.tick_volume or 0.0) > 0]
    current = float(bars[idx].tick_volume or 0.0)
    if not prior or current <= 0:
        return False
    return current >= 1.25 * statistics.median(prior)


def _source_from_displacement(origin, bars: list[Bar]) -> PromptSource | None:
    bar = _bar_by_ts(bars, int(origin.source_ts))
    if bar is None:
        return None
    body_low, body_high = sorted((float(bar.open), float(bar.close)))
    if body_high <= body_low:
        body_low, body_high = float(bar.low), float(bar.high)
    return PromptSource(
        direction=origin.direction,
        tf=str(origin.tf),
        source_ts=int(origin.source_ts),
        core_low=body_low,
        core_high=body_high,
        zone_low=float(bar.low),
        zone_high=float(bar.high),
        strength=float(origin.strength),
        fvg=bool(origin.fvg),
        source_kind="DISPLACEMENT_BOS_SOURCE",
        volume_expansion=_volume_expansion(bars, int(origin.source_ts)),
    )


def _median_range(bars: list[Bar], n: int = 20) -> float:
    values = [float(b.high) - float(b.low) for b in bars[-n:] if float(b.high) > float(b.low)]
    return statistics.median(values) if values else 0.0


def _sweep_rejection_sources(bars: list[Bar], tf: str, max_items: int = 18) -> list[PromptSource]:
    if len(bars) < 30:
        return []
    noise = max(_median_range(bars, 20), atr(bars), 1e-9)
    tolerance = 0.12 * noise
    out: list[PromptSource] = []
    start = max(SWEEP_LOOKBACK, len(bars) - 180)

    for i in range(start, len(bars) - 1):
        bar = bars[i]
        rng = float(bar.high) - float(bar.low)
        if rng <= 0:
            continue
        prior = bars[max(0, i - SWEEP_LOOKBACK):i]
        if len(prior) < 3:
            continue
        prior_high = max(float(x.high) for x in prior)
        prior_low = min(float(x.low) for x in prior)
        body_low, body_high = sorted((float(bar.open), float(bar.close)))
        upper_wick = max(0.0, float(bar.high) - body_high)
        lower_wick = max(0.0, body_low - float(bar.low))
        follow = bars[i + 1:min(len(bars), i + 1 + FOLLOW_THROUGH_BARS)]
        if not follow:
            continue

        sell_raid = float(bar.high) >= prior_high - tolerance and float(bar.close) < prior_high
        sell_reject = upper_wick / rng >= MIN_REJECTION_WICK_FRACTION or float(bar.close) < float(bar.open)
        sell_move = min(float(x.low) for x in follow) <= float(bar.close) - MIN_FOLLOW_THROUGH_ATR * noise
        if sell_raid and sell_reject and sell_move:
            strength = max(2.0, (float(bar.high) - min(float(x.low) for x in follow)) / noise)
            out.append(PromptSource(Direction.SELL, tf, int(bar.ts), body_high, float(bar.high), float(bar.low), float(bar.high), round(strength, 3), False, "LIQUIDITY_SWEEP_REJECTION", _volume_expansion(bars, int(bar.ts))))

        buy_raid = float(bar.low) <= prior_low + tolerance and float(bar.close) > prior_low
        buy_reject = lower_wick / rng >= MIN_REJECTION_WICK_FRACTION or float(bar.close) > float(bar.open)
        buy_move = max(float(x.high) for x in follow) >= float(bar.close) + MIN_FOLLOW_THROUGH_ATR * noise
        if buy_raid and buy_reject and buy_move:
            strength = max(2.0, (max(float(x.high) for x in follow) - float(bar.low)) / noise)
            out.append(PromptSource(Direction.BUY, tf, int(bar.ts), float(bar.low), body_low, float(bar.low), float(bar.high), round(strength, 3), False, "LIQUIDITY_SWEEP_REJECTION", _volume_expansion(bars, int(bar.ts))))

    deduped: list[PromptSource] = []
    for source in reversed(out):
        if any(source.direction == x.direction and not (source.zone_high < x.zone_low or x.zone_high < source.zone_low) for x in deduped):
            continue
        deduped.append(source)
        if len(deduped) >= max_items:
            break
    return list(reversed(deduped))


def _sources(bars: list[Bar], tf: str) -> list[PromptSource]:
    items: list[PromptSource] = []
    for origin in displacement_origins(bars, tf, max_items=24):
        source = _source_from_displacement(origin, bars)
        if source is not None:
            items.append(source)
    items.extend(_sweep_rejection_sources(bars, tf, max_items=24))
    items.sort(key=lambda x: (x.source_ts, x.strength))
    deduped: list[PromptSource] = []
    for source in reversed(items):
        if any(source.direction == x.direction and not (source.zone_high < x.zone_low or x.zone_high < source.zone_low) for x in deduped):
            continue
        deduped.append(source)
        if len(deduped) >= 24:
            break
    return list(reversed(deduped))


def _overlap(a_low: float, a_high: float, b_low: float, b_high: float, pad: float = 0.0) -> bool:
    return not (a_high < b_low - pad or b_high < a_low - pad)


def _build_candidates(snapshot: MarketSnapshot) -> list[PromptCandidate]:
    h4 = _sources(snapshot.xau_h4, "H4")
    h1 = _sources(snapshot.xau_h1, "H1")
    pad = H1_PARENT_OVERLAP_ATR * max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9)
    out: list[PromptCandidate] = []

    for direction in (Direction.BUY, Direction.SELL):
        parents = [x for x in h4 if x.direction == direction]
        children = [x for x in h1 if x.direction == direction]
        used_children: set[int] = set()
        for parent in parents:
            matches = [child for child in children if _overlap(parent.zone_low, parent.zone_high, child.zone_low, child.zone_high, pad)]
            if matches:
                child = max(matches, key=lambda x: (x.source_ts, x.strength))
                used_children.add(id(child))
                out.append(PromptCandidate(direction, "H4>H1", max(parent.source_ts, child.source_ts), child.core_low, child.core_high, parent.zone_low, parent.zone_high, max(parent.strength, child.strength), parent.fvg or child.fvg, f"{parent.source_kind}+{child.source_kind}", parent.volume_expansion or child.volume_expansion, "PROMPT_H4_PARENT_H1_REFINEMENT"))
            else:
                out.append(PromptCandidate(direction, "H4", parent.source_ts, parent.core_low, parent.core_high, parent.zone_low, parent.zone_high, parent.strength, parent.fvg, parent.source_kind, parent.volume_expansion, "PROMPT_H4_SOURCE_CANDLE"))
        for child in children:
            if id(child) in used_children:
                continue
            out.append(PromptCandidate(direction, "H1", child.source_ts, child.core_low, child.core_high, child.zone_low, child.zone_high, child.strength, child.fvg, child.source_kind, child.volume_expansion, "PROMPT_H1_TACTICAL_SOURCE"))
    return out


def _required_liquidity(direction: Direction) -> str:
    return "BSL" if direction == Direction.SELL else "SSL"


def _normalize_core(candidate: PromptCandidate, snapshot: MarketSnapshot) -> tuple[float, float]:
    point = _point(snapshot)
    minimum = CORE_MIN_POINTS * point
    maximum = CORE_MAX_POINTS * point
    lo, hi = sorted((float(candidate.core_low), float(candidate.core_high)))
    width = min(max(max(0.0, hi - lo), minimum), maximum)
    if candidate.direction == Direction.SELL:
        return hi - width, hi
    return lo, lo + width


def _select_liquidity(candidate: PromptCandidate, core_low: float, core_high: float, liq, snapshot: MarketSnapshot):
    required = _required_liquidity(candidate.direction)
    point = _point(snapshot)
    maximum = ENVELOPE_MAX_POINTS * point
    sweep_room = MIN_SWEEP_ROOM_POINTS * point
    source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
    tf_rank = {"D1": 0, "H4": 1, "H1": 2}
    options = []

    for level in liq:
        if required not in str(level.label).upper():
            continue
        tf = str(level.source_tf).upper()
        if tf not in {"D1", "H4", "H1"}:
            continue
        price = float(level.price)
        if candidate.direction == Direction.SELL:
            if price < core_low:
                continue
            hard_high = max(core_high, price + sweep_room)
            if hard_high - core_low > maximum + 1e-9:
                continue
            edge_distance = abs(price - core_high)
        else:
            if price > core_high:
                continue
            hard_low = min(core_low, price - sweep_room)
            if core_high - hard_low > maximum + 1e-9:
                continue
            edge_distance = abs(core_low - price)
        already_in_source = source_low <= price <= source_high
        options.append((0 if already_in_source else 1, tf_rank.get(tf, 9), edge_distance, float(level.distance), level))

    if not options:
        return None
    options.sort(key=lambda row: row[:-1])
    return options[0][-1]


def _build_geometry(candidate: PromptCandidate, core_low: float, core_high: float, level, snapshot: MarketSnapshot) -> tuple[float, float, float] | None:
    point = _point(snapshot)
    minimum = ENVELOPE_MIN_POINTS * point
    maximum = ENVELOPE_MAX_POINTS * point
    sweep_room = MIN_SWEEP_ROOM_POINTS * point
    source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
    liquidity_price = float(level.price)

    if candidate.direction == Direction.SELL:
        hard_high = max(core_high, liquidity_price + sweep_room)
        if hard_high - core_low > maximum + 1e-9:
            return None
        high = min(max(source_high, hard_high), core_low + maximum)
        low = min(source_low, core_low)
        if high - low > maximum:
            low = high - maximum
        if high - low < minimum:
            low = high - minimum
        if low > core_low + 1e-9 or high < hard_high - 1e-9:
            return None
        actual_room = high - liquidity_price
    else:
        hard_low = min(core_low, liquidity_price - sweep_room)
        if core_high - hard_low > maximum + 1e-9:
            return None
        low = max(min(source_low, hard_low), core_high - maximum)
        high = max(source_high, core_high)
        if high - low > maximum:
            high = low + maximum
        if high - low < minimum:
            high = low + minimum
        if low > hard_low + 1e-9 or high < core_high - 1e-9:
            return None
        actual_room = liquidity_price - low

    width = high - low
    if width < minimum - 1e-9 or width > maximum + 1e-9 or actual_room < sweep_room - 1e-9:
        return None
    return low, high, actual_room


def _psy_in_zone(low: float, high: float, liq) -> bool:
    return any(str(x.label).upper() == "PSY" and float(low) <= float(x.price) <= float(high) for x in liq)


def _qualified_mitigations(
    core_low: float,
    core_high: float,
    zone_low: float,
    zone_high: float,
    source_ts: int,
    bars: list[Bar],
    raw_touch_episodes: int = 0,
    *,
    direction: Direction = Direction.SELL,
) -> int:
    """Compatibility wrapper around the professional directional ledger.

    raw_touch_episodes is deliberately not allowed to manufacture freshness.
    Only a completed directionally-correct mitigation cycle can change grade.
    """
    audit = audit_directional_mitigations(
        direction,
        core_low,
        core_high,
        zone_low,
        zone_high,
        source_ts,
        bars,
    )
    return int(audit.get("qualified_mitigations") or 0)


def _mitigation_grade_ledger(
    audit: dict,
    candidate: PromptCandidate,
    location_score: float,
    *,
    countertrend: bool,
    structural_liquidity_tf: str,
    psy_confluence: bool,
) -> dict:
    """Attach the exact grade effect to every mitigation/interation event."""
    enriched = {**audit, "events": []}
    for event in list(audit.get("events") or []):
        before_count = int(event.get("qualified_count_before") or 0)
        after_count = before_count + (1 if event.get("qualified") else 0)
        before = _grade_audit(
            candidate,
            before_count,
            location_score,
            countertrend=countertrend,
            structural_liquidity_tf=structural_liquidity_tf,
            psy_confluence=psy_confluence,
        )["grade"]
        after = _grade_audit(
            candidate,
            after_count,
            location_score,
            countertrend=countertrend,
            structural_liquidity_tf=structural_liquidity_tf,
            psy_confluence=psy_confluence,
        )["grade"]
        enriched["events"].append(
            {
                **event,
                "grade_before": before.value,
                "grade_after": after.value,
                "grade_changed": before != after,
            }
        )
    return enriched

def _grade_audit(
    candidate: PromptCandidate,
    mitigations: int,
    location_score: float,
    *,
    countertrend: bool,
    structural_liquidity_tf: str,
    psy_confluence: bool,
) -> dict:
    """Return the deterministic grade plus the exact criteria that produced it."""
    tf = str(candidate.source_tf).upper()
    liq_tf = str(structural_liquidity_tf).upper()
    htf_liquidity = liq_tf in {"D1", "H4"}
    sweep_rejection = "SWEEP_REJECTION" in str(candidate.source_kind).upper()
    displacement = "DISPLACEMENT_BOS_SOURCE" in str(candidate.source_kind).upper()
    reversal_evidence = sum(
        (
            1 if sweep_rejection else 0,
            1 if candidate.fvg else 0,
            1 if candidate.volume_expansion else 0,
            1 if candidate.strength >= 2.0 else 0,
            1 if psy_confluence else 0,
        )
    )

    if countertrend:
        aplus_checks = {
            "h4_h1_source": tf == "H4>H1",
            "htf_structural_liquidity": htf_liquidity,
            "location_ge_7": location_score >= 7.0,
            "strength_ge_2": candidate.strength >= 2.0,
            "sweep_rejection": sweep_rejection,
            "reversal_evidence_ge_2": reversal_evidence >= 2,
            "mitigations_le_1": mitigations <= 1,
        }
        a_checks = {
            "h4_or_h4_h1_source": tf in {"H4>H1", "H4"},
            "htf_structural_liquidity": htf_liquidity,
            "location_ge_6": location_score >= 6.0,
            "strength_ge_1_6": candidate.strength >= 1.6,
            "sweep_or_displacement": sweep_rejection or displacement,
            "reversal_evidence_ge_1": reversal_evidence >= 1,
            "mitigations_le_2": mitigations <= 2,
        }
        if all(aplus_checks.values()):
            grade = Grade.A_PLUS
        elif all(a_checks.values()):
            grade = Grade.A
        else:
            grade = Grade.B_PLUS
        return {
            "grade": grade,
            "model": "COUNTERTREND_REVERSAL",
            "source_tf": tf,
            "structural_liquidity_tf": liq_tf,
            "location_score": round(float(location_score), 4),
            "source_strength": round(float(candidate.strength), 4),
            "reversal_evidence_count": int(reversal_evidence),
            "sweep_rejection": bool(sweep_rejection),
            "displacement": bool(displacement),
            "fvg": bool(candidate.fvg),
            "volume_expansion": bool(candidate.volume_expansion),
            "psy_confluence": bool(psy_confluence),
            "mitigations": int(mitigations),
            "aplus_checks": aplus_checks,
            "a_checks": a_checks,
            "aplus_missing": [name for name, ok in aplus_checks.items() if not ok],
            "a_missing": [name for name, ok in a_checks.items() if not ok],
        }

    score_parts = {
        "source_tf": 3 if tf == "H4>H1" else 2 if tf == "H4" else 1,
        "strength": 2 if candidate.strength >= 2.0 else 1 if candidate.strength >= 1.6 else 0,
        "fvg": 1 if candidate.fvg else 0,
        "displacement": 1 if displacement else 0,
        "volume_expansion": 1 if candidate.volume_expansion else 0,
        "freshness": 2 if mitigations == 0 else 1 if mitigations == 1 else 0 if mitigations == 2 else -3,
        "location": 1 if location_score >= 7.0 else 0,
    }
    score = int(sum(score_parts.values()))
    if mitigations >= 3:
        grade = Grade.B_PLUS
    elif score >= 8 and mitigations <= 1:
        grade = Grade.A_PLUS
    elif score >= 5 and mitigations <= 2:
        grade = Grade.A
    else:
        grade = Grade.B_PLUS
    return {
        "grade": grade,
        "model": "TREND_CONTINUATION",
        "source_tf": tf,
        "location_score": round(float(location_score), 4),
        "source_strength": round(float(candidate.strength), 4),
        "score": score,
        "score_parts": score_parts,
        "mitigations": int(mitigations),
        "aplus_threshold": "score>=8 and mitigations<=1",
        "a_threshold": "score>=5 and mitigations<=2",
        "aplus_missing": (
            ["mitigations_le_1"] if mitigations > 1 else []
        ) + (["score_ge_8"] if score < 8 else []),
        "a_missing": (
            ["mitigations_le_2"] if mitigations > 2 else []
        ) + (["score_ge_5"] if score < 5 else []),
    }


def _grade(
    candidate: PromptCandidate,
    mitigations: int,
    location_score: float,
    *,
    countertrend: bool,
    structural_liquidity_tf: str,
    psy_confluence: bool,
) -> Grade:
    """Context-specific grade using only information available before entry."""
    return _grade_audit(
        candidate,
        mitigations,
        location_score,
        countertrend=countertrend,
        structural_liquidity_tf=structural_liquidity_tf,
        psy_confluence=psy_confluence,
    )["grade"]


def _dxy(snapshot: MarketSnapshot) -> Direction:
    """Compatibility seam for deterministic DXY context.

    Tests and research overrides can patch this helper without changing how DXY is
    interpreted. DXY remains supporting context only and never manufactures a zone.
    """
    return prompt_dxy_direction(snapshot)


def _dxy_support(direction: Direction, snapshot: MarketSnapshot) -> str:
    dxy = _dxy(snapshot)
    if dxy == Direction.NEUTRAL:
        return "NEUTRAL"
    if (direction == Direction.SELL and dxy == Direction.BUY) or (direction == Direction.BUY and dxy == Direction.SELL):
        return "SUPPORT"
    return "CONFLICT"


def _candidate_zone(candidate: PromptCandidate, snapshot: MarketSnapshot, liq, context: Direction, index: int) -> tuple[Zone | None, dict]:
    core_low, core_high = _normalize_core(candidate, snapshot)
    required = _required_liquidity(candidate.direction)
    attached = _select_liquidity(candidate, core_low, core_high, liq, snapshot)
    base_diag = {
        "direction": candidate.direction.value,
        "source_tf": candidate.source_tf,
        "source_method": candidate.method,
        "source_kind": candidate.source_kind,
        "source_ts": candidate.source_ts,
        "core_low": round(core_low, 5),
        "core_high": round(core_high, 5),
        "core_width_points": round(_to_points(core_high - core_low, snapshot), 1),
        "required_liquidity": required,
    }

    if attached is None:
        return None, {
            **base_diag,
            "zone_low": round(candidate.zone_low, 5),
            "zone_high": round(candidate.zone_high, 5),
            "envelope_width_points": round(_to_points(abs(float(candidate.zone_high) - float(candidate.zone_low)), snapshot), 1),
            "touches": 0,
            "attached_liquidity": "",
            "sweep_room_points": 0.0,
            "distance_h1_atr": round(_distance(snapshot.mid, candidate.zone_low, candidate.zone_high) / max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9), 3),
            "rejection_code": f"MISSING_{required}_IN_MARKED_ZONE",
            "rejection_reason": f"No structural {required} can fit inside a 200-300 point envelope around this source while preserving at least {MIN_SWEEP_ROOM_POINTS:.0f} points beyond the liquidity sweep.",
        }

    geometry = _build_geometry(candidate, core_low, core_high, attached, snapshot)
    if geometry is None:
        return None, {
            **base_diag,
            "zone_low": round(candidate.zone_low, 5),
            "zone_high": round(candidate.zone_high, 5),
            "envelope_width_points": round(_to_points(abs(float(candidate.zone_high) - float(candidate.zone_low)), snapshot), 1),
            "touches": 0,
            "attached_liquidity": f"{attached.label}@{float(attached.price):.5f}",
            "sweep_room_points": 0.0,
            "distance_h1_atr": round(_distance(snapshot.mid, candidate.zone_low, candidate.zone_high) / max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9), 3),
            "rejection_code": "ZONE_GEOMETRY_CANNOT_FIT_SWEEP",
            "rejection_reason": "The core, structural liquidity and required sweep room cannot all fit inside the 200-300 point envelope contract.",
        }

    zone_low, zone_high, sweep_room = geometry
    raw_touch_episodes = _touches(core_low, core_high, int(candidate.source_ts), snapshot.xau_m15)
    core_mid = (core_low + core_high) / 2.0
    loc = _location_score(candidate.direction, core_mid, snapshot, liq)
    countertrend = context not in (Direction.NEUTRAL, candidate.direction)
    psy_confluence = _psy_in_zone(zone_low, zone_high, liq)
    mitigation_audit = audit_directional_mitigations(
        candidate.direction,
        core_low,
        core_high,
        zone_low,
        zone_high,
        int(candidate.source_ts),
        snapshot.xau_m15,
    )
    touches = int(mitigation_audit.get("qualified_mitigations") or 0)
    structural_audit = _grade_audit(
        candidate,
        0,
        loc,
        countertrend=countertrend,
        structural_liquidity_tf=str(getattr(attached, "source_tf", "")),
        psy_confluence=psy_confluence,
    )
    current_audit = _grade_audit(
        candidate,
        touches,
        loc,
        countertrend=countertrend,
        structural_liquidity_tf=str(getattr(attached, "source_tf", "")),
        psy_confluence=psy_confluence,
    )
    structural_grade = structural_audit["grade"]
    grade = current_audit["grade"]
    mitigation_audit = _mitigation_grade_ledger(
        mitigation_audit,
        candidate,
        loc,
        countertrend=countertrend,
        structural_liquidity_tf=str(getattr(attached, "source_tf", "")),
        psy_confluence=psy_confluence,
    )
    grade_degrade_reason = ""
    if structural_grade in {Grade.A_PLUS, Grade.A} and grade == Grade.B_PLUS and touches >= 3:
        grade_degrade_reason = "EXHAUSTED_3PLUS_QUALIFIED_MITIGATIONS"
    elif structural_grade == Grade.A_PLUS and grade == Grade.A:
        grade_degrade_reason = "FRESHNESS_REDUCED"
    elif structural_grade == Grade.B_PLUS:
        grade_degrade_reason = "STRUCTURAL_QUALITY_BELOW_A"
    conf = {"LIQUIDITY_IN_MARKED_ZONE", f"{required}_IN_MARKED_ZONE", "SOURCE_CANDLE_ANCHORED", "CORE_100_150_POINTS", "ENVELOPE_200_300_POINTS", "SWEEP_ROOM_RESERVED"}
    if "DISPLACEMENT_BOS_SOURCE" in candidate.source_kind:
        conf.add("INSTITUTIONAL_DISPLACEMENT")
    if "LIQUIDITY_SWEEP_REJECTION" in candidate.source_kind:
        conf.add("LIQUIDITY_SWEEP_REJECTION")
    if candidate.source_tf == "H4>H1":
        conf.add("H4_H1_OVERLAP")
    if candidate.fvg:
        conf.add("HISTORICAL_DISPLACEMENT_FVG")
    if candidate.volume_expansion:
        conf.add("TICK_VOLUME_EXPANSION")
    if psy_confluence:
        conf.add("PSYCHOLOGICAL_LEVEL_CONFLUENCE")
    if loc >= 7:
        conf.add("PREMIUM_DISCOUNT_EXTREMITY")

    original_targets = _targets(candidate.direction, core_mid, liq)
    flip = candidate.direction.opposite()
    flip_ref = zone_high if flip == Direction.BUY else zone_low
    flip_targets = _targets(flip, float(flip_ref), liq)
    vals = original_targets + [0.0] * (4 - len(original_targets))
    fvals = flip_targets + [0.0] * (4 - len(flip_targets))
    clear_run = abs(float(vals[0]) - core_mid) if vals and vals[0] else 0.0
    readiness = "ARMED" if ((grade == Grade.A_PLUS and touches <= 1) or (grade == Grade.A and touches <= 2)) else "WATCH"

    zone = Zone(
        zone_id=f"PZ_{candidate.source_tf.replace('>','')}_{candidate.direction.value}_{index}",
        original_direction=candidate.direction,
        flip_direction=flip,
        setup_type="REVERSAL" if countertrend else "CONTINUATION",
        source_tf=candidate.source_tf,
        grade=grade,
        state=ZoneState.ACTIVE,
        core_low=round(core_low, 5),
        core_high=round(core_high, 5),
        core_method=f"{readiness}|PROMPT_SWEEP_ROOM_GEOMETRY|{candidate.method}",
        location_score=round(loc, 4),
        zone_low=round(zone_low, 5),
        zone_high=round(zone_high, 5),
        touch_count=touches,
        mitigation_audit=mitigation_audit,
        confluences=sorted(conf),
        independent_confluence_count=len(conf),
        requires_sweep=True,
        source_ts=int(candidate.source_ts),
        invalidation_level=round(zone_high if candidate.direction == Direction.SELL else zone_low, 5),
        invalidation_rule="Closed M15 body acceptance beyond the OUTER 200-300 point envelope invalidates the zone. Wick-only liquidity raids do not invalidate.",
        original_target1=float(vals[0]),
        original_target2=float(vals[1]),
        original_target3=float(vals[2]),
        original_runner=float(vals[3]),
        flip_target1=float(fvals[0]),
        flip_target2=float(fvals[1]),
        flip_target3=float(fvals[2]),
        flip_runner=float(fvals[3]),
        clear_run=round(clear_run, 5),
        countertrend=countertrend,
        dxy_support=_dxy_support(candidate.direction, snapshot),
        notes=[
            f"readiness:{readiness}",
            f"source_candle:{candidate.source_tf}:{candidate.source_ts}",
            f"source_kind:{candidate.source_kind}",
            f"attached_liquidity:{required}:{attached.label}@{float(attached.price):.5f}",
            f"core_width_points:{_to_points(core_high - core_low, snapshot):.1f}",
            f"envelope_width_points:{_to_points(zone_high - zone_low, snapshot):.1f}",
            f"sweep_room_points:{_to_points(sweep_room, snapshot):.1f}",
            f"raw_core_touch_episodes:{raw_touch_episodes}",
            f"qualified_mitigations:{touches}",
            f"structural_grade:{structural_grade.value}",
            f"current_execution_grade:{grade.value}",
            f"grade_degrade_reason:{grade_degrade_reason or 'NONE'}",
            f"structural_aplus_missing:{','.join(structural_audit.get('aplus_missing') or []) or 'NONE'}",
            f"structural_a_missing:{','.join(structural_audit.get('a_missing') or []) or 'NONE'}",
            f"grade_location_score:{float(loc):.4f}",
            f"grade_source_strength:{float(candidate.strength):.4f}",
            f"grade_context:{'COUNTERTREND_REVERSAL' if countertrend else 'TREND_CONTINUATION'}",
            "Core is source-anchored and normalized to 100-150 points. Envelope is 200-300 points and contains the required structural liquidity with reserved distal sweep room.",
            "Qualified mitigation is directional and complete: SELL requires below-envelope -> core -> below-envelope; BUY requires above-envelope -> core -> above-envelope. Wrong-side contacts never consume freshness.",
            "Grade uses only pre-entry structural evidence. Momentum after price leaves the zone validates execution quality but cannot retroactively upgrade the zone.",
            "D1 gives context. H4 is primary. H1 refines/falls back. M15 validates health. M1 only times entry.",
        ],
    )

    state = evaluate_zone_state(zone, snapshot.xau_m15, snapshot.atr_m15)
    diag = {
        **base_diag,
        "zone_low": round(zone_low, 5),
        "zone_high": round(zone_high, 5),
        "envelope_width_points": round(_to_points(zone_high - zone_low, snapshot), 1),
        "touches": touches,
        "raw_touch_episodes": raw_touch_episodes,
        "structural_grade": structural_grade.value,
        "current_execution_grade": grade.value,
        "grade_degrade_reason": grade_degrade_reason or "NONE",
        "structural_grade_audit": {
            **{k: v for k, v in structural_audit.items() if k != "grade"},
            "grade": structural_grade.value,
        },
        "current_grade_audit": {
            **{k: v for k, v in current_audit.items() if k != "grade"},
            "grade": grade.value,
        },
        "grade_context": "COUNTERTREND_REVERSAL" if countertrend else "TREND_CONTINUATION",
        "attached_liquidity": f"{attached.label}@{float(attached.price):.5f}",
        "sweep_room_points": round(_to_points(sweep_room, snapshot), 1),
        "distance_h1_atr": round(_distance(snapshot.mid, zone_low, zone_high) / max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9), 3),
        "grade": grade.value,
        "mitigation_audit": mitigation_audit,
        "mitigation_invalidated_at": int(mitigation_audit.get("invalidated_at") or 0),
        "mitigation_invalidation_reason": str(mitigation_audit.get("invalidation_reason") or ""),
    }
    if int(mitigation_audit.get("invalidated_at") or 0) > 0:
        return None, {
            **diag,
            "rejection_code": "HISTORICAL_M15_ACCEPTED_INVALIDATION",
            "rejection_reason": "The original zone had already received accepted M15 invalidation after its source formed. Mitigation counting stopped at that timestamp; later crossings belong to flip/reclaim logic.",
        }
    if state != ZoneState.ACTIVE:
        return None, {**diag, "rejection_code": "M15_ACCEPTED_INVALIDATION", "rejection_reason": "Closed M15 price has accepted beyond the outer envelope. Wick-only raids are allowed; accepted body closes are not."}
    return zone, {**diag, "rejection_code": "", "rejection_reason": ""}


def _rank(zone: Zone, snapshot: MarketSnapshot) -> tuple:
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(zone.source_tf, 9)
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 9}.get(zone.grade, 9)
    return (tf_rank, grade_rank, int(zone.touch_count), 0 if "HISTORICAL_DISPLACEMENT_FVG" in zone.confluences else 1, 0 if "TICK_VOLUME_EXPANSION" in zone.confluences else 1, -float(zone.location_score), _distance(snapshot.mid, zone.zone_low, zone.zone_high), -int(zone.source_ts))


def _readiness(zone: Zone) -> str:
    method = str(zone.core_method or "")
    return method.split("|", 1)[0] if "|" in method else "WATCH"


def _set_readiness(zone: Zone, readiness: str) -> None:
    old = str(zone.core_method or "")
    tail = old.split("|", 1)[1] if "|" in old else old
    zone.core_method = f"{readiness}|{tail}" if tail else readiness
    zone.notes = [f"readiness:{readiness}" if str(note).startswith("readiness:") else note for note in zone.notes]


def _zone_health_allows_interaction(zone: Zone, snapshot: MarketSnapshot) -> bool:
    if zone.state != ZoneState.ACTIVE or zone.grade not in {Grade.A_PLUS, Grade.A, Grade.B_PLUS}:
        return False
    if evaluate_zone_state(zone, snapshot.xau_m15, snapshot.atr_m15) != ZoneState.ACTIVE:
        return False
    return "LIQUIDITY_IN_MARKED_ZONE" in set(zone.confluences)


def primary_zone_interacting(zone: Zone, snapshot: MarketSnapshot) -> bool:
    """True only when the live quote actually overlaps the tactical core.

    INTERACTING is user-facing state truth, so ATR proximity must not manufacture
    a contact that has not happened. The quote spread may overlap the core even if
    the midpoint sits just outside it, therefore use bid/ask rather than midpoint.
    """
    if not _zone_health_allows_interaction(zone, snapshot):
        return False
    bid = float(snapshot.bid)
    ask = float(snapshot.ask)
    lo, hi = sorted((float(zone.core_low), float(zone.core_high)))
    return ask >= lo and bid <= hi


def primary_zone_approaching(zone: Zone, snapshot: MarketSnapshot) -> bool:
    """Pre-refresh trigger only: keep the old ATR proximity without relabelling the zone."""
    if not _zone_health_allows_interaction(zone, snapshot):
        return False
    if primary_zone_interacting(zone, snapshot):
        return True
    m15a = max(float(snapshot.atr_m15 or atr(snapshot.xau_m15)), 1e-9)
    buffer_price = max(_point(snapshot) * 5.0, APPROACH_BUFFER_M15_ATR * m15a)
    return _distance(snapshot.mid, zone.core_low, zone.core_high) <= buffer_price


def _note_float(zone: Zone, prefix: str) -> float:
    for note in zone.notes:
        text = str(note)
        if text.startswith(prefix):
            try:
                return float(text.split(":", 1)[1])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def apply_two_zone_institutional_map(analysis: Analysis, snapshot: MarketSnapshot) -> list[Zone]:
    """One prompt-driven zone per side with explicit point-width and sweep-room geometry."""
    candidates = _build_candidates(snapshot)
    context = analysis.overall_bias
    accepted = {Direction.BUY: [], Direction.SELL: []}
    diagnostics = {Direction.BUY: [], Direction.SELL: []}

    for index, candidate in enumerate(candidates, 1):
        zone, diag = _candidate_zone(candidate, snapshot, analysis.liquidity_map, context, index)
        diagnostics[candidate.direction].append(diag)
        if zone is not None:
            accepted[candidate.direction].append(zone)

    chosen: dict[Direction, Zone] = {}
    for direction in (Direction.SELL, Direction.BUY):
        side = accepted[direction]
        if side:
            side.sort(key=lambda z: _rank(z, snapshot))
            chosen[direction] = side[0]

    order = [Direction.SELL, Direction.BUY] if context == Direction.SELL else [Direction.BUY, Direction.SELL] if context == Direction.BUY else [Direction.SELL, Direction.BUY]
    analysis.zones = [chosen[d] for d in order if d in chosen]
    for zone in analysis.zones:
        _set_readiness(zone, "INTERACTING" if primary_zone_interacting(zone, snapshot) else _readiness(zone))

    executable = [z for z in analysis.zones if z.state == ZoneState.ACTIVE and execution_grade_eligible(z)]
    preferred = next((z for z in executable if z.original_direction == context), None)
    if preferred is None and executable:
        preferred = min(executable, key=lambda z: _distance(snapshot.mid, z.core_low, z.core_high))
    analysis.selected_zone_id = preferred.zone_id if preferred is not None else ""

    public: dict[str, dict] = {}
    labels: list[str] = []
    for zone in analysis.zones:
        required = _required_liquidity(zone.original_direction)
        attached = next((n for n in zone.notes if str(n).startswith("attached_liquidity:")), "")
        core_points = _to_points(float(zone.core_high) - float(zone.core_low), snapshot)
        envelope_points = _to_points(float(zone.zone_high) - float(zone.zone_low), snapshot)
        sweep_points = _note_float(zone, "sweep_room_points:")
        structural_grade = next(
            (str(n).split(":", 1)[1] for n in zone.notes if str(n).startswith("structural_grade:")),
            zone.grade.value,
        )
        raw_touch_episodes = int(_note_float(zone, "raw_core_touch_episodes:"))
        degrade_reason = next(
            (str(n).split(":", 1)[1] for n in zone.notes if str(n).startswith("grade_degrade_reason:")),
            "NONE",
        )
        public[zone.original_direction.value.lower()] = {
            "zone_id": zone.zone_id,
            "state": _readiness(zone),
            "source_tf": zone.source_tf,
            "structural_grade": structural_grade,
            "grade": zone.grade.value,
            "grade_degrade_reason": degrade_reason,
            "structural_aplus_missing": next((str(n).split(":",1)[1] for n in zone.notes if str(n).startswith("structural_aplus_missing:")), "NONE"),
            "structural_a_missing": next((str(n).split(":",1)[1] for n in zone.notes if str(n).startswith("structural_a_missing:")), "NONE"),
            "grade_location_score": _note_float(zone, "grade_location_score:"),
            "grade_source_strength": _note_float(zone, "grade_source_strength:"),
            "low": zone.zone_low,
            "high": zone.zone_high,
            "core_low": zone.core_low,
            "core_high": zone.core_high,
            "core_width_points": round(core_points, 1),
            "envelope_width_points": round(envelope_points, 1),
            "sweep_room_points": round(sweep_points, 1),
            "touches": zone.touch_count,
            "qualified_mitigations": zone.touch_count,
            "raw_core_touch_episodes": raw_touch_episodes,
            "mitigation_audit": dict(zone.mitigation_audit or {}),
            "mitigation_expected_approach_side": str((zone.mitigation_audit or {}).get("expected_approach_side") or ""),
            "mitigation_counting_stopped": bool((zone.mitigation_audit or {}).get("counting_stopped")),
            "required_liquidity": required,
            "liquidity_in_zone": True,
            "attached_liquidity": attached,
            "source_ts": zone.source_ts,
        }
        labels.append(
            f"{zone.original_direction.value}={zone.zone_low:.2f}-{zone.zone_high:.2f} "
            f"(core={zone.core_low:.2f}-{zone.core_high:.2f},{zone.source_tf},"
            f"structural={structural_grade},current={zone.grade.value},{_readiness(zone)},"
            f"mitigations={zone.touch_count},raw_contacts={raw_touch_episodes},"
            f"{required}=IN_ZONE,sweep_room={sweep_points:.0f}pt)"
        )

    rejected_summary: dict[str, dict] = {}
    for direction in (Direction.SELL, Direction.BUY):
        rows = diagnostics[direction]
        rejected = [x for x in rows if x.get("rejection_code")]
        strongest = None
        if rejected:
            tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}
            strongest = sorted(rejected, key=lambda x: (tf_rank.get(str(x.get("source_tf")), 9), int(x.get("touches") or 0), float(x.get("distance_h1_atr") or 999.0), -int(x.get("source_ts") or 0)))[0]
        rejected_summary[direction.value.lower()] = {
            "candidate_count": len(rows),
            "rejected_count": len(rejected),
            "strongest_rejected": strongest,
            "summary": "ZONE_SELECTED" if direction in chosen else strongest.get("rejection_code") if strongest else "NO_VALID_H4_H1_SOURCE_CANDLE",
        }

    policy = dict(analysis.execution_policy or {})
    policy["public_zone_map"] = {
        "engine": "PROMPT_ZONE_ENGINE_2026_09_14_SWEEP_ROOM",
        "map_count": len(analysis.zones),
        "max_zones": 2,
        "one_per_side": True,
        "sell_requires_bsl_in_marked_zone": True,
        "buy_requires_ssl_in_marked_zone": True,
        "core_width_points_min": CORE_MIN_POINTS,
        "core_width_points_max": CORE_MAX_POINTS,
        "envelope_width_points_min": ENVELOPE_MIN_POINTS,
        "envelope_width_points_max": ENVELOPE_MAX_POINTS,
        "min_sweep_room_points": MIN_SWEEP_ROOM_POINTS,
        "liquidity_must_be_inside_envelope": True,
        "sweep_room_beyond_liquidity_must_be_inside_envelope": True,
        "h4_primary_h1_refine_or_fallback": True,
        "m15_health_only": True,
        "m1_timing_only": True,
        "distance_is_not_a_hard_zone_filter": True,
        "psy_is_confluence_not_qualification": True,
        "dxy_is_confirmation_not_qualification": True,
        "mitigation_count_affects_grade_not_zone_geometry": True,
        "touch_count_semantics": "DIRECTIONAL_COMPLETE_CORE_MITIGATIONS_ONLY",
        "sell_mitigation_cycle": "BELOW_ENVELOPE_TO_CORE_TO_BELOW_ENVELOPE",
        "buy_mitigation_cycle": "ABOVE_ENVELOPE_TO_CORE_TO_ABOVE_ENVELOPE",
        "wrong_side_core_contact_consumes_freshness": False,
        "accepted_invalidation_stops_original_zone_counting": True,
        "context_specific_grade_models": {
            "TREND": "CONTINUATION_SOURCE_STRENGTH_FRESHNESS",
            "COUNTERTREND": "HTF_EXTREMITY_LIQUIDITY_SWEEP_REJECTION_RESPONSE",
        },
        "post_reaction_profit_never_upgrades_historical_grade": True,
        "dual_grade_truth": {
            "structural_grade": "SOURCE_QUALITY_BEFORE_REUSE_FRESHNESS_PENALTY",
            "current_execution_grade": "STRUCTURAL_GRADE_AFTER_QUALIFIED_MITIGATION_FRESHNESS",
            "execution_uses_current_execution_grade_only": True,
        },
        "wick_only_does_not_invalidate": True,
        "rejected_diagnostics": rejected_summary,
        **public,
    }
    analysis.execution_policy = policy
    summary = "; ".join(labels) if labels else "none"
    analysis.trader_brief = f"D1 context={context.value}. Prompt sweep-room map: {summary}. Trend and countertrend use separate A+/A qualification models: trend grades continuation-source strength/freshness; countertrend grades HTF extremity + structural liquidity raid/rejection + reversal response quality. The map now reports structural grade separately from current execution grade: a structurally A+/A zone can become current B+ after repeated qualified reuse without rewriting what the source quality was. Qualified mitigations are directional complete cycles: SELL below->core->below; BUY above->core->above. Wrong-side contacts and post-invalidation crossings never consume freshness. Core width is 100-150 points. Outer envelope is 200-300 points. SELL requires structural BSL inside the envelope with at least 50 points reserved above it for a raid; BUY requires structural SSL inside the envelope with at least 50 points reserved below it. H4 is primary; H1 refines or falls back. M15 checks accepted invalidation. Distance, PSY and DXY do not manufacture zones. M1 remains entry timing only. Post-reaction profit never retroactively upgrades the zone grade."
    return analysis.zones


def build_prompt_analysis(snapshot: MarketSnapshot, generated_at: int | None = None) -> Analysis:
    now = generated_at or int(datetime.now(timezone.utc).timestamp())
    liq = liquidity_map(snapshot)
    context = structure_bias(snapshot.xau_d1)
    structural = [x for x in liq if "BSL" in x.label.upper() or "SSL" in x.label.upper()]
    if context == Direction.SELL:
        preferred = sorted([x for x in structural if "SSL" in x.label.upper() and x.price < snapshot.mid], key=lambda x: x.distance)
    elif context == Direction.BUY:
        preferred = sorted([x for x in structural if "BSL" in x.label.upper() and x.price > snapshot.mid], key=lambda x: x.distance)
    else:
        preferred = sorted(structural, key=lambda x: x.distance)
    primary = preferred[0] if preferred else sorted(structural, key=lambda x: x.distance)[0] if structural else None

    guards: list[str] = []
    if not prompt_snapshot_complete(snapshot):
        guards.append("NO_COMPLETE_HISTORY_CONTEXT")
    if snapshot.spread_points > SETTINGS.max_spread_points:
        guards.append(f"SPREAD_HIGH:{snapshot.spread_points:.1f}")
    if now - snapshot.sent_at > SETTINGS.max_snapshot_age_seconds:
        guards.append("SNAPSHOT_STALE")
    # Spread is an execution-time safety hold, not a reason to erase a valid
    # institutional thesis. Keep it visible in guards and let /mt5/plan live_block
    # suspend orders. Structural analysis/ownership may still be acquired so the
    # thesis survives until spread normalizes.
    hard_block = "NO_COMPLETE_HISTORY_CONTEXT" in guards or "SNAPSHOT_STALE" in guards
    usd_news = [{"ts": int(n.ts), "title": str(n.title), "impact": str(n.impact)} for n in snapshot.news if str(n.currency).upper() == "USD"]

    analysis = Analysis(
        analysis_id=f"A_{now}_{uuid.uuid4().hex[:8]}",
        generated_at=now,
        snapshot_at=snapshot.sent_at,
        overall_bias=context,
        primary_liquidity=f"{primary.label}@{primary.price:.5f}" if primary else "",
        liquidity_map=liq,
        zones=[],
        selected_zone_id="",
        trader_brief="",
        approved=not hard_block,
        prompt_version="SMC_PROMPT_ZONE_ENGINE_2026_09_14_SWEEP_ROOM",
        execution_policy={
            "core": "PROMPT_D1_H4_H1_M15_SWEEP_ROOM_GEOMETRY_M1_TIMING",
            "market_structure": {
                "xau_d1": structure_bias(snapshot.xau_d1).value,
                "xau_h4": structure_bias(snapshot.xau_h4).value,
                "xau_h1": structure_bias(snapshot.xau_h1).value,
                "xau_m15": structure_bias(snapshot.xau_m15).value,
                "dxy_d1": structure_bias(snapshot.dxy_d1).value,
                "dxy_h1": structure_bias(snapshot.dxy_h1).value,
            },
            "market_inputs": {
                "atr_h1": float(snapshot.atr_h1 or atr(snapshot.xau_h1)),
                "atr_m15": float(snapshot.atr_m15 or atr(snapshot.xau_m15)),
                "spread_points": float(snapshot.spread_points),
                "usd_news": usd_news,
                "prompt_snapshot_complete": prompt_snapshot_complete(snapshot),
                "dxy_confirmation_timeframes": ["D1", "H1"],
            },
            "zone_geometry": {
                "core_width_points": [CORE_MIN_POINTS, CORE_MAX_POINTS],
                "envelope_width_points": [ENVELOPE_MIN_POINTS, ENVELOPE_MAX_POINTS],
                "minimum_sweep_room_points": MIN_SWEEP_ROOM_POINTS,
                "sell_sweep_room_side": "ABOVE_BSL",
                "buy_sweep_room_side": "BELOW_SSL",
            },
            "primary": ["D1_CONTEXT", "H4_SOURCE_LOCATION", "H1_REFINEMENT_OR_FALLBACK", "CORE_100_150_POINTS", "ENVELOPE_200_300_POINTS", "STRUCTURAL_BSL_OR_SSL_INSIDE_ENVELOPE", "MINIMUM_50_POINT_DISTAL_SWEEP_ROOM", "DISPLACEMENT_BOS_OR_SWEEP_REJECTION", "FVG_CONFLUENCE_IF_PRESENT", "MITIGATION_COUNT", "M15_ACCEPTED_INVALIDATION", "M1_SWEEP_MSS_DISPLACEMENT_VALUE_ENTRY"],
            "reentry": ["THESIS_VALID", "OBJECTIVE_OPEN", "CONTINUATION_BOS", "NEW_DISPLACEMENT", "NEW_M1_DEALING_RANGE", "INTERNAL_LIQUIDITY", "PREMIUM_DISCOUNT", "FRESH_PD_ARRAY"],
            "flip": ["M15_ACCEPTANCE_INVALIDATION", "NO_INSTANT_REVERSE", "OPPOSITE_SIDE_RETEST", "M1_MSS_BOS", "DISPLACEMENT", "NEW_M1_DEALING_RANGE", "PREMIUM_DISCOUNT", "OTE", "FRESH_PD_ARRAY"],
            "risk": ["ONE_BUDGET_PER_THESIS", "NO_AVERAGING_DOWN", "NO_SL_WIDENING", "STRUCTURE_AWARE_BE", "LIQUIDITY_PARTIALS", "M5_ATR_RUNNER_TRAIL"],
        },
        guards=guards,
    )
    apply_two_zone_institutional_map(analysis, snapshot)
    return analysis
