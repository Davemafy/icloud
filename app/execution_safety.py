from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .engine import atr
from .models import Analysis, Feedback, Grade, MarketSnapshot, Zone, ZoneState

# DEMO/PAPER execution safety contract. The wide HTF envelope is location/sweep
# context only. Primary M1 authority begins at the tactical core (or a very small
# volatility buffer around it). Re-entry keeps its separate protected-position
# contract after a valid primary. Every active target must remain on the profitable
# side of the actual candidate entry.
CORE_INTERACTION_BUFFER_M15_ATR = 0.10
CORE_INTERACTION_MIN_POINTS = 5.0
TARGET_MIN_POINTS = 5.0
TARGET_SPREAD_MULTIPLIER = 1.50
EXECUTION_GUARD_CONTRACT = "CORE_ONLY_TARGET_DIRECTION_V6512"
THESIS_CONTINUATION_STATUSES = {"REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}


def _readiness(zone: Zone | None) -> str:
    if zone is None:
        return ""
    method = str(zone.core_method or "")
    return method.split("|", 1)[0] if "|" in method else method


def _selected_zone(analysis: Analysis | None) -> Zone | None:
    if analysis is None or not analysis.selected_zone_id:
        return None
    return next((z for z in analysis.zones if z.zone_id == analysis.selected_zone_id), None)


def _distance_to_range(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def core_interaction_buffer(snapshot: MarketSnapshot) -> float:
    m15a = max(float(snapshot.atr_m15 or atr(snapshot.xau_m15)), float(snapshot.point), 1e-9)
    return max(float(snapshot.point) * CORE_INTERACTION_MIN_POINTS, m15a * CORE_INTERACTION_BUFFER_M15_ATR)


def core_is_interacting(zone: Zone, snapshot: MarketSnapshot, price: float | None = None) -> bool:
    px = float(snapshot.mid if price is None else price)
    return _distance_to_range(px, float(zone.core_low), float(zone.core_high)) <= core_interaction_buffer(snapshot)


def target_min_gap(snapshot: MarketSnapshot) -> float:
    return max(
        float(snapshot.point) * TARGET_MIN_POINTS,
        float(snapshot.point) * float(snapshot.spread_points) * TARGET_SPREAD_MULTIPLIER,
    )


def _dedupe(values: list[float]) -> list[float]:
    out: list[float] = []
    for value in values:
        if value <= 0:
            continue
        if any(abs(value - existing) <= 1e-9 for existing in out):
            continue
        out.append(value)
    return out


def _filter_targets(direction: str, values: list[float], reference: float, gap: float) -> tuple[list[float], int]:
    direction = str(direction).upper()
    values = _dedupe([float(v) for v in values if float(v) > 0])
    if direction == "BUY":
        valid = [v for v in values if v > reference + gap]
        valid.sort()
    else:
        valid = [v for v in values if v < reference - gap]
        valid.sort(reverse=True)
    return valid, max(0, len(values) - len(valid))


def _pack_targets(kv: dict[str, str], prefix: str, values: list[float]) -> None:
    keys = [f"{prefix}_target1", f"{prefix}_target2", f"{prefix}_target3", f"{prefix}_runner"]
    packed = values[:4] + [0.0] * max(0, 4 - len(values))
    for key, value in zip(keys, packed):
        kv[key] = f"{float(value):.5f}"


def _parse_plan(text: str) -> tuple[list[str], dict[str, str]]:
    order: list[str] = []
    kv: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if key not in kv:
            order.append(key)
        kv[key] = value.strip()
    return order, kv


def _serialize_plan(order: list[str], kv: dict[str, str]) -> str:
    final_order = list(order)
    for key in kv:
        if key not in final_order:
            final_order.append(key)
    return "".join(f"{key}={kv[key]}\n" for key in final_order)


def _confirmed_thesis_bplus_override(analysis: Analysis, zone: Zone, plan_state: str) -> bool:
    """Permit only a confirmed surviving B+ thesis to reuse the execution handoff.

    A normal fresh B+ zone remains WATCH_ONLY. This exception exists solely when
    the same zone already produced an institutional reaction, still owns the thesis,
    has returned to M1_READY through the strict core handoff, and deterministic/AI
    approvals are still valid. It therefore repairs the legacy A/A+ export gate
    without weakening new-zone qualification.
    """
    if not SETTINGS.paper_only:
        return False
    if zone.grade != Grade.B_PLUS or zone.state != ZoneState.ACTIVE:
        return False
    if str(plan_state).upper() != ZoneState.ACTIVE.value:
        return False
    if _readiness(zone) != "M1_READY":
        return False
    if "THESIS_CONTINUATION" not in str(zone.core_method or ""):
        return False
    if not bool(analysis.approved):
        return False
    if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and not bool(analysis.ai_approved):
        return False

    meta = dict((analysis.execution_policy or {}).get("active_thesis") or {})
    return bool(
        meta.get("locked")
        and meta.get("continuation_authority")
        and str(meta.get("status") or "") in THESIS_CONTINUATION_STATUSES
        and str(meta.get("owner_zone_id") or "") == zone.zone_id
        and str(meta.get("direction") or "") == zone.original_direction.value
        and bool(meta.get("owner_zone_present", True))
        and bool(meta.get("objective_open", True))
    )


def guard_plan_text(text: str, analysis: Analysis | None, snapshot: MarketSnapshot | None) -> str:
    """Fail closed before primary core handoff and sanitize all exported objectives.

    The running DEMO Sequence 3.23 already obeys ea_mode and plan targets, so this
    protection is effective from the cloud without requiring a local MT5 binary
    replacement. Re-entry remains governed by the EA's existing protected-position
    rules once a valid M1_READY primary thesis exists.
    """
    if analysis is None or snapshot is None:
        return text
    zone = _selected_zone(analysis)
    if zone is None:
        return text

    order, kv = _parse_plan(text)
    base_mode = str(kv.get("ea_mode", "WATCH_ONLY")).upper()
    readiness = _readiness(zone)
    core_now = core_is_interacting(zone, snapshot)
    cloud_ready = readiness == "M1_READY"
    plan_state = str(kv.get("zone_state", zone.state.value)).upper()
    thesis_bplus_override = _confirmed_thesis_bplus_override(analysis, zone, plan_state)
    effective_mode = "DUAL_BRANCH" if thesis_bplus_override else base_mode
    handoff_ready = bool(cloud_ready and effective_mode == "DUAL_BRANCH")

    kv["execution_guard_contract"] = EXECUTION_GUARD_CONTRACT
    kv["core_interaction_basis"] = "TACTICAL_CORE_ONLY_FOR_PRIMARY"
    kv["core_interaction_buffer"] = f"{core_interaction_buffer(snapshot):.5f}"
    kv["core_interaction_now"] = "1" if core_now else "0"
    kv["core_handoff_ready"] = "1" if handoff_ready else "0"
    kv["thesis_continuation_bplus_override"] = "1" if thesis_bplus_override else "0"
    kv["zone_setup_type_original"] = str(zone.setup_type)

    # Static objective sanitation: an original target must be beyond the profitable
    # edge of the entire tactical core, so it cannot become a wrong-side TP for a
    # legitimate primary entry anywhere inside that core.
    point_gap = max(float(snapshot.point) * CORE_INTERACTION_MIN_POINTS, 1e-9)
    original_values = [
        float(zone.original_target1),
        float(zone.original_target2),
        float(zone.original_target3),
        float(zone.original_runner),
    ]
    original_reference = float(zone.core_high) if zone.original_direction.value == "BUY" else float(zone.core_low)
    original_valid, original_removed = _filter_targets(
        zone.original_direction.value,
        original_values,
        original_reference,
        point_gap,
    )

    # Live objective sanitation: even after primary handoff, re-entry can occur at a
    # different price. Require all targets exported on this poll to remain beyond
    # the current executable side by at least spread-aware clearance.
    live_reference = float(snapshot.ask if zone.original_direction.value == "BUY" else snapshot.bid)
    live_valid, live_removed = _filter_targets(
        zone.original_direction.value,
        original_valid,
        live_reference,
        target_min_gap(snapshot),
    )
    exported_original = live_valid if handoff_ready else original_valid
    _pack_targets(kv, "original", exported_original)
    kv["original_targets_removed_wrong_side"] = str(original_removed)
    kv["live_targets_removed_wrong_side"] = str(live_removed)
    kv["original_target_direction_valid"] = "1" if original_valid else "0"
    kv["live_target_direction_valid"] = "1" if (not handoff_ready or bool(live_valid)) else "0"

    # Flip objectives are anchored beyond the failed outer envelope because a flip
    # may only exist after accepted invalidation and opposite-side retest.
    flip_values = [
        float(zone.flip_target1),
        float(zone.flip_target2),
        float(zone.flip_target3),
        float(zone.flip_runner),
    ]
    flip_reference = float(zone.zone_high) if zone.flip_direction.value == "BUY" else float(zone.zone_low)
    flip_valid, flip_removed = _filter_targets(
        zone.flip_direction.value,
        flip_values,
        flip_reference,
        point_gap,
    )
    _pack_targets(kv, "flip", flip_valid)
    kv["flip_targets_removed_wrong_side"] = str(flip_removed)
    kv["flip_target_direction_valid"] = "1" if flip_valid else "0"

    guard_reasons: list[str] = []
    if not cloud_ready:
        guard_reasons.append("CLOUD_M1_HANDOFF_NOT_READY")
    if not original_valid:
        guard_reasons.append("NO_DIRECTIONALLY_VALID_ORIGINAL_TARGET")
    if handoff_ready and not live_valid:
        guard_reasons.append("LIVE_TARGET_DIRECTION_INVALID")

    if handoff_ready and original_valid and live_valid:
        kv["ea_mode"] = "DUAL_BRANCH"
        if thesis_bplus_override:
            # Once a reversal zone has already reacted, a later first execution is
            # continuation of that confirmed thesis. This lets Sequence 3.23 use its
            # normal continuation-capable primary router without relabeling the map.
            kv["setup_type"] = "CONTINUATION"
            kv["execution_role"] = "THESIS_CONTINUATION"
    else:
        kv["ea_mode"] = "WATCH_ONLY"
    kv["execution_guard_reason"] = ",".join(guard_reasons)
    return _serialize_plan(order, kv)


def live_target_guard_reasons(text: str, snapshot: MarketSnapshot | None) -> list[str]:
    """Optional external check for callers that want a separate live-block reason."""
    if snapshot is None:
        return []
    _, kv = _parse_plan(text)
    if str(kv.get("ea_mode", "")).upper() != "DUAL_BRANCH":
        return []
    if str(kv.get("live_target_direction_valid", "1")) != "1":
        return ["LIVE_TARGET_DIRECTION_INVALID"]
    return []


def normalize_candidate_feedback(
    feedback: Feedback,
    analysis: Analysis | None,
    snapshot: MarketSnapshot | None,
) -> Feedback:
    """Normalize observer-only telemetry to the live core/target safety contract."""
    if snapshot is None or analysis is None or str(feedback.event).upper() != "ML_CANDIDATE":
        return feedback
    if feedback.analysis_id and feedback.analysis_id != analysis.analysis_id:
        return feedback
    if not isinstance(feedback.details, dict):
        return feedback

    zone = next((z for z in analysis.zones if z.zone_id == feedback.zone_id), None)
    if zone is None:
        return feedback

    out = feedback.model_copy(deep=True)
    details: dict[str, Any] = dict(out.details)
    features = dict(details.get("features") or {})
    role = str(features.get("role", "")).upper()
    candidate_direction = str(details.get("direction", "")).upper()
    is_flip = role.startswith("FLIP") or (
        candidate_direction in {"BUY", "SELL"} and candidate_direction != zone.original_direction.value
    )

    # Primary candidates require tactical-core context. Re-entry deliberately does
    # not: it already has its own existing-position/protected-thesis gate.
    if not is_flip and role == "PRIMARY":
        px = float(details.get("entry_price") or out.price or snapshot.mid)
        core_now = core_is_interacting(zone, snapshot, px)
        cloud_ready = _readiness(zone) == "M1_READY"
        features["zone_context"] = 1 if core_now else 0
        features["recent_zone_interaction"] = 1 if (core_now or cloud_ready) else 0
        features["interaction_basis"] = "TACTICAL_CORE_ONLY_FOR_PRIMARY"
        features["core_interaction_buffer"] = round(core_interaction_buffer(snapshot), 5)
        if not core_now and not cloud_ready:
            reasons = list(details.get("rejection_reasons") or [])
            if "CORE_NOT_REACHED" not in reasons:
                reasons.append("CORE_NOT_REACHED")
            details["rejection_reasons"] = reasons
            details["eligible"] = False

    entry = float(details.get("entry_price") or out.price or 0.0)
    gap = target_min_gap(snapshot)
    wrong_target = False
    if candidate_direction in {"BUY", "SELL"} and entry > 0:
        for key in ("target1", "target2", "target3"):
            try:
                target = float(details.get(key) or 0.0)
            except (TypeError, ValueError):
                target = 0.0
            if target <= 0:
                continue
            ok = target > entry + gap if candidate_direction == "BUY" else target < entry - gap
            if not ok:
                details[key] = 0.0
                wrong_target = True
    features["target_direction_valid"] = 0 if wrong_target else 1
    features["target_min_gap"] = round(gap, 5)
    if wrong_target:
        reasons = list(details.get("rejection_reasons") or [])
        if "TARGET_DIRECTION_INVALID" not in reasons:
            reasons.append("TARGET_DIRECTION_INVALID")
        details["rejection_reasons"] = reasons
        details["eligible"] = False

    details["features"] = features
    out.details = details
    return out
