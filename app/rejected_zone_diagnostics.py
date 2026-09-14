from __future__ import annotations

from typing import Any

from .engine import atr
from .models import Analysis, Direction, Grade, MarketSnapshot, ZoneState


def _reason(code: str, detail: str) -> tuple[str, str]:
    return code, detail


def _diagnostic_rank(zone, candidate, snapshot: MarketSnapshot) -> tuple:
    """Rank rejected candidates by the same institutional priorities used by the map."""
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(str(candidate.source_tf), 9)
    strength = max((float(x.strength) for x in candidate.components), default=0.0)
    has_fvg = any(bool(x.fvg) for x in candidate.components)
    h1a = max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9)
    mid = float(snapshot.mid)
    lo, hi = sorted((float(zone.core_low), float(zone.core_high)))
    distance = 0.0 if lo <= mid <= hi else (lo - mid if mid < lo else mid - hi)
    distance_h1_atr = distance / h1a
    return (
        tf_rank,
        0 if strength >= 2.0 else 1,
        0 if has_fvg else 1,
        int(zone.touch_count),
        distance_h1_atr,
        -float(zone.location_score),
        -strength,
        -int(candidate.source_ts),
    )


def _evaluate_candidate(analysis: Analysis, snapshot: MarketSnapshot, zid: str, index: int, candidate) -> dict[str, Any] | None:
    """Return first hard rejection for one candidate, or None if it passes the public-map gates."""
    from . import institutional_two_zone as iz

    context = iz.daily_context(snapshot)
    zone = iz.build_zone(candidate, snapshot, analysis.liquidity_map, context, index)
    touches = iz._core_touches(zone, candidate, snapshot)
    zone.touch_count = touches
    required = iz._required_liquidity_kind(zone.original_direction)
    strength = iz._max_strength(candidate)
    source_method = str(candidate.method or "")
    reason_code = ""
    reason_text = ""
    attached_label = ""

    if touches > iz.MAX_PRIMARY_TOUCHES:
        reason_code, reason_text = _reason(
            "TOO_MANY_CORE_MITIGATIONS",
            f"Core has {touches} reaction episodes; maximum primary allowance is {iz.MAX_PRIMARY_TOUCHES}.",
        )
    else:
        iz._compact_envelope(zone, snapshot)
        attached = iz._attached_liquidity(zone, analysis, snapshot)
        if attached is None:
            reason_code, reason_text = _reason(
                f"MISSING_ATTACHED_{required}",
                f"No structural {required} is inside/attached to the compact marked source area.",
            )
        elif not iz._attach_liquidity_to_marked_zone(zone, attached, snapshot):
            reason_code, reason_text = _reason(
                "MARKED_ZONE_TOO_WIDE",
                "Attaching the required structural liquidity would make the marked zone wider than the intraday limit.",
            )
        else:
            attached_label = f"{attached.label}@{float(attached.price):.5f}"
            h1a = max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9)
            distance_h1_atr = iz._distance(float(snapshot.mid), float(zone.zone_low), float(zone.zone_high)) / h1a
            if distance_h1_atr > iz.MAX_PRIMARY_DISTANCE_H1_ATR:
                reason_code, reason_text = _reason(
                    "BEYOND_INTRADAY_REACH",
                    f"Candidate is {distance_h1_atr:.2f} H1 ATR from price; maximum is {iz.MAX_PRIMARY_DISTANCE_H1_ATR:.2f}.",
                )
            else:
                if zone.state == ZoneState.RETIRED and touches <= iz.MAX_PRIMARY_TOUCHES:
                    zone.state = ZoneState.ACTIVE
                zone.state = iz.evaluate_zone_state(zone, snapshot.xau_m15, snapshot.atr_m15)
                if zone.state != ZoneState.ACTIVE:
                    reason_code, reason_text = _reason(
                        "M15_ACCEPTED_INVALIDATION",
                        f"M15 health evaluation returned {zone.state.value}; wick-only raids do not cause this rejection.",
                    )
                else:
                    displaced = "INSTITUTIONAL_DISPLACEMENT" in zone.confluences or strength >= 2.0
                    if not displaced:
                        reason_code, reason_text = _reason(
                            "NO_INSTITUTIONAL_DISPLACEMENT",
                            f"Source strength {strength:.2f} does not meet the institutional displacement requirement.",
                        )
                    elif float(zone.clear_run) <= 0:
                        reason_code, reason_text = _reason(
                            "NO_CLEAR_RUN",
                            "No valid liquidity objective remains open from the candidate source.",
                        )
                    elif iz._conceptual_confluence_count(zone.confluences) < 2:
                        reason_code, reason_text = _reason(
                            "INSUFFICIENT_INDEPENDENT_CONFLUENCE",
                            "Candidate has fewer than two independent institutional confluence groups.",
                        )
                    else:
                        if candidate.source_tf in iz.H4_PARENT_SOURCES and zone.grade not in {Grade.A_PLUS, Grade.A}:
                            zone.grade = Grade.A
                        if zone.grade not in {Grade.A_PLUS, Grade.A}:
                            reason_code, reason_text = _reason(
                                "GRADE_BELOW_A",
                                f"Final candidate grade is {zone.grade.value}; public primary map requires A+ or A.",
                            )

    if not reason_code:
        return None

    h1a = max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9)
    distance_h1_atr = iz._distance(float(snapshot.mid), float(zone.zone_low), float(zone.zone_high)) / h1a
    return {
        "zone_id": zid,
        "direction": zone.original_direction.value,
        "source_tf": str(candidate.source_tf),
        "source_method": source_method,
        "source_ts": int(candidate.source_ts),
        "core_low": round(float(zone.core_low), 5),
        "core_high": round(float(zone.core_high), 5),
        "zone_low": round(float(zone.zone_low), 5),
        "zone_high": round(float(zone.zone_high), 5),
        "touches": int(touches),
        "required_liquidity": required,
        "attached_liquidity": attached_label,
        "strength": round(float(strength), 3),
        "location_score": round(float(zone.location_score), 4),
        "distance_h1_atr": round(float(distance_h1_atr), 3),
        "grade": zone.grade.value,
        "rejection_code": reason_code,
        "rejection_reason": reason_text,
        "rank": _diagnostic_rank(zone, candidate, snapshot),
    }


def build_rejected_zone_diagnostics(analysis: Analysis, snapshot: MarketSnapshot) -> dict[str, Any]:
    """Strongest rejected BUY/SELL with exact first public-map rejection reason."""
    from . import institutional_two_zone as iz

    rows: dict[Direction, list[dict[str, Any]]] = {Direction.BUY: [], Direction.SELL: []}
    counts: dict[Direction, int] = {Direction.BUY: 0, Direction.SELL: 0}

    for zid, index, candidate in iz._candidate_rows(snapshot):
        direction = candidate.direction
        if direction not in rows:
            continue
        counts[direction] += 1
        diagnostic = _evaluate_candidate(analysis, snapshot, zid, index, candidate)
        if diagnostic is not None:
            rows[direction].append(diagnostic)

    result: dict[str, Any] = {}
    for direction, key in ((Direction.SELL, "sell"), (Direction.BUY, "buy")):
        rejected = rows[direction]
        rejected.sort(key=lambda x: tuple(x.pop("rank")))
        strongest = rejected[0] if rejected else None
        if counts[direction] == 0:
            summary = "NO_HTF_SOURCE_CANDIDATE"
        elif strongest is None:
            summary = "NO_REJECTED_CANDIDATE"
        else:
            summary = strongest["rejection_code"]
        result[key] = {
            "candidate_count": counts[direction],
            "rejected_count": len(rejected),
            "summary": summary,
            "strongest_rejected": strongest,
        }
    return result


def attach_rejected_zone_diagnostics(analysis: Analysis, snapshot: MarketSnapshot) -> None:
    if analysis is None:
        return
    policy = dict(analysis.execution_policy or {})
    public = dict(policy.get("public_zone_map") or {})
    public["rejected_diagnostics"] = build_rejected_zone_diagnostics(analysis, snapshot)
    public["diagnostics_paper_only"] = True
    public["diagnostics_do_not_relax_filters"] = True
    policy["public_zone_map"] = public
    analysis.execution_policy = policy


def install_rejected_zone_diagnostics() -> None:
    """Wrap public-map construction so diagnostics are attached before service saves analysis."""
    from . import institutional_two_zone as iz

    current = iz.apply_two_zone_institutional_map
    if getattr(current, "_tradezone_rejected_diagnostics", False):
        return

    def wrapped(analysis: Analysis, snapshot: MarketSnapshot):
        zones = current(analysis, snapshot)
        attach_rejected_zone_diagnostics(analysis, snapshot)
        return zones

    wrapped._tradezone_rejected_diagnostics = True
    iz.apply_two_zone_institutional_map = wrapped
