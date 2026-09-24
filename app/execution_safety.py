from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .engine import atr
from .models import Analysis, Feedback, Grade, MarketSnapshot, Zone, ZoneState
from .risk_matrix import (
    RISK_MODEL,
    execution_grade_eligible,
    flip_risk_pct,
    original_risk_pct,
    zone_risk_context,
)
from .target_revalidation import TARGET_REVALIDATION_CONTRACT, target_ladder_truth

# DEMO/PAPER execution safety contract. Primary M1 SEARCH authority may begin at
# the tactical core OR after a qualified outer-envelope interaction proves the
# attached structural liquidity was swept and reclaimed. Neither is an entry. A
# confirmed structural-liquidity reversal remains a separate authority. Sequence
# still requires its M1 confirmation/value-entry pattern before any order.
CORE_INTERACTION_BUFFER_M15_ATR = 0.10
CORE_INTERACTION_MIN_POINTS = 5.0
TARGET_MIN_POINTS = 5.0
TARGET_SPREAD_MULTIPLIER = 1.50
EXECUTION_GUARD_CONTRACT = "ZONE_SWEEP_OR_CORE_TARGET_DIRECTION_V6528"
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


def live_directional_targets(zone: Zone, snapshot: MarketSnapshot) -> list[float]:
    """Return only still-profitable original objectives from the live execution price.

    This is the cloud-side pre-ownership guard.  A historical/remote thesis may
    remain valid as context, but it cannot acquire fresh execution ownership after
    price has already traded through every same-direction objective.
    """
    direction = zone.original_direction.value
    reference = float(snapshot.ask if direction == "BUY" else snapshot.bid)
    values = [
        float(zone.original_target1 or 0.0),
        float(zone.original_target2 or 0.0),
        float(zone.original_target3 or 0.0),
        float(zone.original_runner or 0.0),
    ]
    valid, _ = _filter_targets(direction, values, reference, target_min_gap(snapshot))
    return valid


def has_live_directional_target(zone: Zone, snapshot: MarketSnapshot) -> bool:
    return bool(live_directional_targets(zone, snapshot))


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

    # Sequence v3.38's legacy KV reader searches for the first occurrence of
    # "execution_authority=" anywhere in the text, not strictly at line start.
    # The context-grade field "bplus_execution_authority=0" can therefore shadow
    # the real global authority when it appears first. Keep the exact global key
    # immediately after ea_mode so older MT5 parsers read the intended value.
    if "execution_authority" in final_order:
        final_order.remove("execution_authority")
        try:
            insert_at = final_order.index("ea_mode") + 1
        except ValueError:
            insert_at = 0
        final_order.insert(insert_at, "execution_authority")

    return "".join(f"{key}={kv[key]}\n" for key in final_order)


def _confirmed_thesis_bplus_override(analysis: Analysis, zone: Zone, plan_state: str) -> bool:
    """Legacy compatibility seam. B+ is context-only in the V2 risk matrix."""
    return False


def _paper_ai_fallback_allows(analysis: Analysis, zone: Zone) -> bool:
    """Allow deterministic PAPER authority to survive an external AI outage."""
    if not SETTINGS.paper_only or not bool(analysis.approved):
        return False
    if not execution_grade_eligible(zone) or zone.state != ZoneState.ACTIVE:
        return False
    fallback = dict((analysis.execution_policy or {}).get("paper_ai_fallback") or {})
    if not bool(fallback.get("active")):
        return False
    return str(fallback.get("authority") or "") in {
        "HTF_CORE_HANDOFF",
        "HTF_ZONE_SWEEP_HANDOFF",
        "LIQUIDITY_REVERSAL_HANDOFF",
    }


def _active_owner_continuation(analysis: Analysis, zone: Zone) -> tuple[bool, str, dict[str, Any]]:
    """Return the sticky authority already earned by a live thesis owner.

    Macro authority is historical once acquired. Leaving the original HTF core or
    envelope must not turn the plan back into WATCH_ONLY while the owner is still
    nonterminal. Sequence remains responsible for fresh M1 BOS/displacement/value
    and no-chase entry timing.
    """
    meta = dict((analysis.execution_policy or {}).get("active_thesis") or {})
    authority = str(meta.get("ownership_authority") or "")
    if not SETTINGS.paper_only or not bool(analysis.approved):
        return False, authority, meta
    if zone.state != ZoneState.ACTIVE or not execution_grade_eligible(zone):
        return False, authority, meta
    if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and not bool(analysis.ai_approved):
        fallback = dict((analysis.execution_policy or {}).get("paper_ai_fallback") or {})
        if not bool(fallback.get("active")):
            return False, authority, meta
    ready = bool(
        meta.get("locked")
        and meta.get("continuation_authority")
        and str(meta.get("status") or "") in THESIS_CONTINUATION_STATUSES
        and str(meta.get("owner_zone_id") or "") == zone.zone_id
        and str(meta.get("direction") or "") == zone.original_direction.value
        and bool(meta.get("owner_zone_present", True))
        and bool(meta.get("objective_open", True))
        and authority in {
            "HTF_CORE_HANDOFF",
            "HTF_ZONE_SWEEP_HANDOFF",
            "LIQUIDITY_REVERSAL_HANDOFF",
        }
    )
    return ready, authority, meta


def _owner_progress_open_targets(analysis: Analysis, zone: Zone) -> tuple[list[float], dict[str, Any]]:
    """Return only still-open owner objectives after TP progress."""
    meta = dict((analysis.execution_policy or {}).get("active_thesis") or {})
    is_owner = bool(
        meta.get("locked")
        and str(meta.get("owner_zone_id") or "") == zone.zone_id
        and str(meta.get("direction") or "") == zone.original_direction.value
    )
    raw = [
        float(zone.original_target1 or 0.0),
        float(zone.original_target2 or 0.0),
        float(zone.original_target3 or 0.0),
    ]
    if not is_owner:
        values = [v for v in raw if v > 0]
        if float(zone.original_runner or 0.0) > 0:
            values.append(float(zone.original_runner))
        return values, meta

    best = float(meta.get("best_price") or 0.0)
    direction = zone.original_direction.value
    out: list[float] = []
    for idx, target in enumerate(raw, start=1):
        if target <= 0:
            continue
        hit_at = int(meta.get(f"target{idx}_hit_at") or 0)
        crossed = bool(
            best > 0
            and (
                (direction == "SELL" and best <= target)
                or (direction == "BUY" and best >= target)
            )
        )
        if not hit_at and not crossed:
            out.append(target)
    runner = float(zone.original_runner or 0.0)
    if runner > 0:
        out.append(runner)
    return out, meta


def _liquidity_handoff_ready(analysis: Analysis, zone: Zone) -> tuple[bool, dict[str, Any]]:
    if not SETTINGS.paper_only or not bool(analysis.approved):
        return False, {}
    meta = dict((analysis.execution_policy or {}).get("liquidity_reversal_handoff") or {})
    if not bool(meta.get("active")):
        return False, meta
    if str(meta.get("authority") or "") != "LIQUIDITY_REVERSAL_HANDOFF":
        return False, meta
    if str(meta.get("context_zone_id") or "") != zone.zone_id:
        return False, meta
    if str(meta.get("direction") or "") != zone.original_direction.value:
        return False, meta
    if not execution_grade_eligible(zone) or zone.state != ZoneState.ACTIVE:
        return False, meta
    if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and not bool(analysis.ai_approved):
        fallback = dict((analysis.execution_policy or {}).get("paper_ai_fallback") or {})
        if not bool(fallback.get("active")):
            return False, meta
    return True, meta


def guard_plan_text(text: str, analysis: Analysis | None, snapshot: MarketSnapshot | None) -> str:
    """Fail closed unless one of the two explicit PAPER execution authorities is active."""
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
    paper_ai_fallback = _paper_ai_fallback_allows(analysis, zone)
    owner_continuation_ready, owner_authority, owner_continuation_meta = _active_owner_continuation(analysis, zone)
    effective_mode = "DUAL_BRANCH" if (owner_continuation_ready or thesis_bplus_override or paper_ai_fallback) else base_mode
    primary_handoff_ready = bool(cloud_ready and effective_mode == "DUAL_BRANCH")
    window = dict((analysis.execution_policy or {}).get("execution_window") or {})
    authority_meta = dict((analysis.execution_policy or {}).get("execution_authority") or {})
    sweep_note = any(
        str(note).startswith("execution_location:LATCHED_AFTER_ZONE_SWEEP")
        or "ZONE_SWEEP_HANDOFF" in str(note)
        for note in zone.notes
    )
    sweep_handoff_ready = bool(
        primary_handoff_ready
        and (
            (
                str(window.get("mode") or "") == "LATCHED_AFTER_ZONE_SWEEP"
                and bool(window.get("sweep_confirmed"))
            )
            or str(authority_meta.get("authority") or "") == "HTF_ZONE_SWEEP_HANDOFF"
            or sweep_note
        )
    )
    core_handoff_ready = bool(primary_handoff_ready and not sweep_handoff_ready)
    liquidity_handoff_ready, lrh = _liquidity_handoff_ready(analysis, zone)
    handoff_ready = bool(owner_continuation_ready or core_handoff_ready or sweep_handoff_ready or liquidity_handoff_ready)

    authority = (
        owner_authority if owner_continuation_ready
        else "HTF_ZONE_SWEEP_HANDOFF" if sweep_handoff_ready
        else "HTF_CORE_HANDOFF" if core_handoff_ready
        else "LIQUIDITY_REVERSAL_HANDOFF" if liquidity_handoff_ready
        else "NONE"
    )
    kv["execution_guard_contract"] = EXECUTION_GUARD_CONTRACT
    kv["execution_authority"] = authority
    kv["core_interaction_basis"] = (
        "OUTER_ZONE_PLUS_PROVEN_LIQUIDITY_SWEEP" if sweep_handoff_ready
        else "TACTICAL_CORE_OR_LATCHED_CORE_REACTION"
    )
    kv["core_interaction_buffer"] = f"{core_interaction_buffer(snapshot):.5f}"
    kv["core_interaction_now"] = "1" if core_now else "0"
    kv["core_handoff_ready"] = "1" if core_handoff_ready else "0"
    kv["owner_continuation_ready"] = "1" if owner_continuation_ready else "0"
    kv["owner_continuation_authority"] = owner_authority if owner_continuation_ready else "NONE"
    kv["zone_sweep_handoff_ready"] = "1" if sweep_handoff_ready else "0"
    kv["zone_sweep_confirmed"] = "1" if bool(window.get("sweep_confirmed")) else "0"
    kv["zone_sweep_ts"] = str(int(window.get("sweep_ts") or 0))
    kv["zone_sweep_label"] = str(window.get("sweep_label") or "")
    kv["zone_sweep_price"] = f"{float(window.get('sweep_price') or 0.0):.5f}"
    kv["core_required_for_authority"] = (
        "0"
        if sweep_handoff_ready
        or (owner_continuation_ready and owner_authority in {"HTF_ZONE_SWEEP_HANDOFF", "LIQUIDITY_REVERSAL_HANDOFF"})
        else "1"
    )
    kv["liquidity_handoff_ready"] = "1" if liquidity_handoff_ready else "0"
    kv["paper_ai_fallback_active"] = "1" if paper_ai_fallback else "0"
    kv["thesis_continuation_bplus_override"] = "1" if thesis_bplus_override else "0"
    kv["zone_setup_type_original"] = str(zone.setup_type)
    base_risk_pct = original_risk_pct(zone)
    kv["risk_model"] = RISK_MODEL
    kv["risk_epoch"] = SETTINGS.research_risk_epoch
    kv["validation_initial_capital"] = f"{SETTINGS.research_validation_initial_capital:.2f}"
    kv["risk_context"] = zone_risk_context(zone)
    kv["grade_risk_pct"] = f"{float(base_risk_pct):.2f}"
    kv["original_risk_pct"] = f"{float(base_risk_pct):.2f}"
    kv["flip_risk_pct"] = f"{float(flip_risk_pct(zone)):.2f}"
    kv["bplus_reduced_risk"] = "0"
    kv["bplus_execution_authority"] = "0"

    handoff_ts = 0
    if owner_continuation_ready:
        handoff_ts = int(
            owner_continuation_meta.get("reaction_confirmed_at")
            or owner_continuation_meta.get("ownership_acquired_at")
            or analysis.snapshot_at
            or analysis.generated_at
            or 0
        )
    elif sweep_handoff_ready:
        handoff_ts = int(window.get("sweep_ts") or 0)
    elif core_handoff_ready:
        handoff_ts = int(window.get("core_touched_at") or analysis.snapshot_at or analysis.generated_at or 0)
    elif liquidity_handoff_ready:
        handoff_ts = int(lrh.get("displacement_ts") or lrh.get("sweep_ts") or 0)
    kv["execution_handoff_ts"] = str(handoff_ts)

    if owner_continuation_ready and owner_authority == "LIQUIDITY_REVERSAL_HANDOFF":
        kv["liquidity_reversal_direction"] = str(owner_continuation_meta.get("direction") or zone.original_direction.value)
        kv["liquidity_reversal_label"] = "PERSISTED_THESIS_OWNER"
        kv["liquidity_reversal_source_tf"] = str(owner_continuation_meta.get("source_tf") or zone.source_tf)
        kv["liquidity_reversal_price"] = f"{float(owner_continuation_meta.get('ownership_anchor_price') or 0.0):.5f}"
        kv["liquidity_reversal_sweep_ts"] = "0"
        kv["liquidity_reversal_displacement_ts"] = str(handoff_ts)
        kv["liquidity_reversal_risk_multiplier"] = "0.50"
        kv["liquidity_object_promoted_to_zone"] = "0"
    elif liquidity_handoff_ready:
        kv["liquidity_reversal_direction"] = str(lrh.get("direction") or "")
        kv["liquidity_reversal_label"] = str(lrh.get("liquidity_label") or "")
        kv["liquidity_reversal_source_tf"] = str(lrh.get("liquidity_source_tf") or "")
        kv["liquidity_reversal_price"] = f"{float(lrh.get('liquidity_price') or 0.0):.5f}"
        kv["liquidity_reversal_sweep_ts"] = str(int(lrh.get("sweep_ts") or 0))
        kv["liquidity_reversal_displacement_ts"] = str(int(lrh.get("displacement_ts") or 0))
        kv["liquidity_reversal_risk_multiplier"] = f"{float(lrh.get('risk_multiplier') or 0.50):.2f}"
        kv["liquidity_object_promoted_to_zone"] = "0"

    point_gap = max(float(snapshot.point) * CORE_INTERACTION_MIN_POINTS, 1e-9)
    original_values, owner_meta = _owner_progress_open_targets(analysis, zone)
    original_reference = float(zone.core_high) if zone.original_direction.value == "BUY" else float(zone.core_low)
    original_valid, original_removed = _filter_targets(
        zone.original_direction.value,
        original_values,
        original_reference,
        point_gap,
    )

    live_reference = float(snapshot.ask if zone.original_direction.value == "BUY" else snapshot.bid)
    live_valid, live_removed = _filter_targets(
        zone.original_direction.value,
        original_valid,
        live_reference,
        target_min_gap(snapshot),
    )

    target_truth = target_ladder_truth(analysis, zone, snapshot)
    target_truth_enforced = bool(
        int(target_truth.get("publication_ts") or 0) > 0
        or bool(target_truth.get("owner"))
    )
    truth_open = [float(x) for x in list(target_truth.get("open_targets") or [])]
    if target_truth_enforced:
        exported_original = truth_open
        live_valid = truth_open
        original_valid = truth_open
    else:
        exported_original = live_valid if handoff_ready else original_valid

    _pack_targets(kv, "original", exported_original)
    kv["original_targets_removed_wrong_side"] = str(original_removed)
    kv["live_targets_removed_wrong_side"] = str(live_removed)
    kv["owner_target_progress_applied"] = "1" if bool(owner_meta.get("locked")) and str(owner_meta.get("owner_zone_id") or "") == zone.zone_id else "0"
    kv["next_open_target"] = f"{float(exported_original[0] if exported_original else 0.0):.5f}"
    kv["original_target_direction_valid"] = "1" if original_valid else "0"
    kv["live_target_direction_valid"] = "1" if (not handoff_ready or bool(live_valid)) else "0"
    kv["target_revalidation_contract"] = TARGET_REVALIDATION_CONTRACT
    kv["target_revalidation_enforced"] = "1" if target_truth_enforced else "0"
    kv["target_revalidation_status"] = str(target_truth.get("status") or "UNAVAILABLE")
    kv["target_history_complete"] = "1" if bool(target_truth.get("history_complete")) else "0"
    kv["target_remap_required"] = "1" if bool(target_truth.get("remap_required")) else "0"
    kv["target_authority_safe"] = "1" if (not target_truth_enforced or bool(target_truth.get("authority_safe"))) else "0"
    kv["target_activation_reference"] = f"{float(target_truth.get('activation_reference') or 0.0):.5f}"
    kv["target_activation_reference_basis"] = str(target_truth.get("activation_reference_basis") or "")
    for item in list(target_truth.get("objectives") or []):
        label = str(item.get("label") or "").lower()
        if label:
            kv[f"target_state_{label}"] = str(item.get("state") or "")
            kv[f"target_reason_{label}"] = str(item.get("reason") or "")

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
    target_authority_safe = bool(
        not target_truth_enforced or target_truth.get("authority_safe")
    )
    if not handoff_ready:
        guard_reasons.append("NO_EXECUTION_HANDOFF")
    if not original_valid:
        guard_reasons.append("NO_DIRECTIONALLY_VALID_ORIGINAL_TARGET")
    if handoff_ready and not live_valid:
        guard_reasons.append("LIVE_TARGET_DIRECTION_INVALID")
    if handoff_ready and target_truth_enforced and not target_authority_safe:
        target_reason = (
            "TARGET_HISTORY_UNVERIFIED"
            if str(target_truth.get("status") or "") == "HISTORY_UNVERIFIED_BLOCK"
            else "TARGET_REMAP_REQUIRED"
        )
        guard_reasons.append(target_reason)
        handoff_ready = False
        authority = "NONE"
        kv["execution_authority"] = "NONE"
        kv["core_handoff_ready"] = "0"
        kv["owner_continuation_ready"] = "0"
        kv["owner_continuation_authority"] = "NONE"
        kv["zone_sweep_handoff_ready"] = "0"
        kv["liquidity_handoff_ready"] = "0"

    if handoff_ready and original_valid and live_valid and target_authority_safe:
        kv["ea_mode"] = "DUAL_BRANCH"
        if owner_continuation_ready:
            kv["setup_type"] = "CONTINUATION"
            kv["execution_role"] = "THESIS_CONTINUATION"
        elif thesis_bplus_override:
            kv["setup_type"] = "CONTINUATION"
            kv["execution_role"] = "THESIS_CONTINUATION"
        elif sweep_handoff_ready:
            kv["execution_role"] = "ZONE_SWEEP_PRIMARY"
        elif liquidity_handoff_ready:
            kv["execution_role"] = "LIQUIDITY_REVERSAL_HANDOFF"
    else:
        kv["ea_mode"] = "WATCH_ONLY"
    kv["execution_guard_reason"] = ",".join(guard_reasons)
    return _serialize_plan(order, kv)


def live_target_guard_reasons(text: str, snapshot: MarketSnapshot | None) -> list[str]:
    if snapshot is None:
        return []
    _, kv = _parse_plan(text)
    if str(kv.get("ea_mode", "")).upper() != "DUAL_BRANCH":
        return []
    reasons: list[str] = []
    if str(kv.get("live_target_direction_valid", "1")) != "1":
        reasons.append("LIVE_TARGET_DIRECTION_INVALID")
    if str(kv.get("target_revalidation_enforced", "0")) == "1" and str(kv.get("target_authority_safe", "1")) != "1":
        reasons.append(
            "TARGET_HISTORY_UNVERIFIED"
            if str(kv.get("target_revalidation_status", "")) == "HISTORY_UNVERIFIED_BLOCK"
            else "TARGET_REMAP_REQUIRED"
        )
    return reasons


def normalize_candidate_feedback(
    feedback: Feedback,
    analysis: Analysis | None,
    snapshot: MarketSnapshot | None,
) -> Feedback:
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

    lrh = dict((analysis.execution_policy or {}).get("liquidity_reversal_handoff") or {})
    lrh_primary = bool(
        lrh.get("active")
        and str(lrh.get("context_zone_id") or "") == zone.zone_id
        and str(lrh.get("direction") or "") == candidate_direction
    )
    owner_continuation_ready, owner_authority, owner_meta = _active_owner_continuation(analysis, zone)
    owner_primary = bool(
        owner_continuation_ready
        and str(owner_meta.get("direction") or "") == candidate_direction
    )

    if not is_flip and role == "PRIMARY":
        px = float(details.get("entry_price") or out.price or snapshot.mid)
        core_now = core_is_interacting(zone, snapshot, px)
        cloud_ready = _readiness(zone) == "M1_READY"
        window = dict((analysis.execution_policy or {}).get("execution_window") or {})
        authority_meta = dict((analysis.execution_policy or {}).get("execution_authority") or {})
        sweep_note = any(
            str(note).startswith("execution_location:LATCHED_AFTER_ZONE_SWEEP")
            or "ZONE_SWEEP_HANDOFF" in str(note)
            for note in zone.notes
        )
        sweep_primary = bool(
            cloud_ready
            and (
                (
                    str(window.get("mode") or "") == "LATCHED_AFTER_ZONE_SWEEP"
                    and bool(window.get("sweep_confirmed"))
                )
                or str(authority_meta.get("authority") or "") == "HTF_ZONE_SWEEP_HANDOFF"
                or sweep_note
            )
        )
        features["zone_context"] = 1 if (core_now or sweep_primary or owner_primary) else 0
        features["recent_zone_interaction"] = 1 if (core_now or cloud_ready or lrh_primary or owner_primary) else 0
        features["owner_continuation"] = 1 if owner_primary else 0
        features["owner_continuation_authority"] = owner_authority if owner_primary else "NONE"
        features["interaction_basis"] = (
            "PERSISTED_THESIS_OWNER" if owner_primary
            else "LIQUIDITY_REVERSAL_HANDOFF" if lrh_primary
            else "OUTER_ZONE_PLUS_PROVEN_LIQUIDITY_SWEEP" if sweep_primary
            else "TACTICAL_CORE_OR_LATCHED_CORE_REACTION"
        )
        features["core_interaction_buffer"] = round(core_interaction_buffer(snapshot), 5)
        features["zone_sweep_handoff"] = 1 if sweep_primary else 0
        features["zone_sweep_ts"] = int(window.get("sweep_ts") or 0)
        features["zone_sweep_price"] = float(window.get("sweep_price") or 0.0)
        features["liquidity_reversal_handoff"] = 1 if lrh_primary else 0
        if not core_now and not cloud_ready and not lrh_primary and not owner_primary:
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