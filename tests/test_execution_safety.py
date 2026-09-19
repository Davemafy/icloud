from app.execution_safety import guard_plan_text, normalize_candidate_feedback
from app.models import Analysis, Direction, Feedback, Grade, MarketSnapshot, Zone, ZoneState


def _snapshot(mid: float, spread_points: float = 18.0) -> MarketSnapshot:
    half = spread_points * 0.01 / 2.0
    return MarketSnapshot(
        sent_at=1,
        bid=mid - half,
        ask=mid + half,
        spread_points=spread_points,
        point=0.01,
        atr_h1=20.0,
        atr_m15=6.0,
    )


def _sell_zone(readiness: str = "M1_READY") -> Zone:
    return Zone(
        zone_id="PZ_H4H1_SELL_10",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=4305.88,
        core_high=4315.88,
        core_method=f"{readiness}|PROMPT_SWEEP_ROOM_GEOMETRY|PROMPT_H4_PARENT_H1_REFINEMENT",
        location_score=9.0,
        zone_low=4282.75,
        zone_high=4322.75,
        touch_count=1,
        independent_confluence_count=6,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "BSL_IN_MARKED_ZONE"],
        source_ts=1,
        invalidation_level=4322.75,
        invalidation_rule="M15 accepted invalidation",
        original_target1=4310.0,
        original_target2=4300.54,
        original_target3=4300.0,
        flip_target1=4324.05,
        flip_target2=4324.68,
        flip_target3=4326.29,
        clear_run=1.0,
    )


def _buy_bplus_thesis_zone(readiness: str = "M1_READY|THESIS_CONTINUATION") -> Zone:
    return Zone(
        zone_id="PZ_H4H1_BUY_4",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="REVERSAL",
        source_tf="H4>H1",
        grade=Grade.B_PLUS,
        state=ZoneState.ACTIVE,
        core_low=4253.57,
        core_high=4270.98,
        core_method=f"{readiness}|PROMPT_SWEEP_ROOM_GEOMETRY|PROMPT_H4_PARENT_H1_REFINEMENT",
        location_score=8.0,
        zone_low=4248.57,
        zone_high=4288.57,
        touch_count=2,
        independent_confluence_count=6,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "SSL_IN_MARKED_ZONE"],
        source_ts=1789390800,
        invalidation_level=4248.57,
        invalidation_rule="M15 accepted invalidation",
        original_target1=4297.83,
        original_target2=4317.38,
        original_target3=4322.93,
        flip_target1=4019.09,
        flip_target2=3995.91,
        clear_run=26.85,
    )


def _analysis(zone: Zone) -> Analysis:
    return Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )


def _confirmed_buy_thesis_analysis(zone: Zone, *, ai_approved: bool = True) -> Analysis:
    a = _analysis(zone)
    a.ai_approved = ai_approved
    a.execution_policy = {
        "active_thesis": {
            "locked": True,
            "direction": "BUY",
            "status": "REACTION_CONFIRMED",
            "owner_zone_id": zone.zone_id,
            "owner_zone_present": True,
            "continuation_authority": True,
            "objective_open": True,
        }
    }
    return a


def _kv(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def test_sell_plan_removes_target_inside_core_and_keeps_only_profit_side_objectives():
    zone = _sell_zone("M1_READY")
    snap = _snapshot(4306.50)
    raw = (
        "ea_mode=DUAL_BRANCH\n"
        "original_direction=SELL\n"
        "original_target1=4310.00000\n"
        "original_target2=4300.54000\n"
        "original_target3=4300.00000\n"
        "original_runner=0.00000\n"
        "flip_target1=4324.05000\n"
        "flip_target2=4324.68000\n"
        "flip_target3=4326.29000\n"
        "flip_runner=0.00000\n"
    )
    out = _kv(guard_plan_text(raw, _analysis(zone), snap))
    assert out["ea_mode"] == "DUAL_BRANCH"
    assert out["execution_authority"] == "HTF_CORE_HANDOFF"
    assert float(out["original_target1"]) == 4300.54
    assert float(out["original_target2"]) == 4300.0
    assert float(out["original_target3"]) == 0.0
    assert out["original_targets_removed_wrong_side"] == "1"
    assert out["live_target_direction_valid"] == "1"


def test_armed_zone_cannot_export_executable_plan_before_any_handoff():
    zone = _sell_zone("ARMED")
    snap = _snapshot(4290.0)
    raw = "ea_mode=DUAL_BRANCH\noriginal_direction=SELL\noriginal_target1=4300.00000\n"
    out = _kv(guard_plan_text(raw, _analysis(zone), snap))
    assert out["ea_mode"] == "WATCH_ONLY"
    assert out["core_handoff_ready"] == "0"
    assert out["liquidity_handoff_ready"] == "0"
    assert out["execution_authority"] == "NONE"
    assert "NO_EXECUTION_HANDOFF" in out["execution_guard_reason"]


def test_liquidity_reversal_handoff_can_export_dual_branch_without_promoting_liquidity_to_zone():
    zone = _sell_zone("ARMED")
    zone.original_target1 = 4280.0
    zone.original_target2 = 4270.0
    zone.original_target3 = 4260.0
    analysis = _analysis(zone)
    analysis.execution_policy = {
        "liquidity_reversal_handoff": {
            "active": True,
            "authority": "LIQUIDITY_REVERSAL_HANDOFF",
            "direction": "SELL",
            "context_zone_id": zone.zone_id,
            "liquidity_label": "H1_BSL",
            "liquidity_source_tf": "H1",
            "liquidity_price": 4350.0,
            "sweep_ts": 10,
            "displacement_ts": 20,
            "risk_multiplier": 0.50,
        }
    }
    snap = _snapshot(4290.0, spread_points=16.0)
    raw = (
        "ea_mode=WATCH_ONLY\n"
        "original_direction=SELL\n"
        "original_target1=4280.00000\n"
        "original_target2=4270.00000\n"
        "original_target3=4260.00000\n"
    )
    out = _kv(guard_plan_text(raw, analysis, snap))
    assert out["ea_mode"] == "DUAL_BRANCH"
    assert out["execution_authority"] == "LIQUIDITY_REVERSAL_HANDOFF"
    assert out["core_handoff_ready"] == "0"
    assert out["liquidity_handoff_ready"] == "1"
    assert out["execution_role"] == "LIQUIDITY_REVERSAL_HANDOFF"
    assert out["liquidity_object_promoted_to_zone"] == "0"
    assert out["liquidity_reversal_risk_multiplier"] == "0.50"


def test_confirmed_bplus_owner_can_export_thesis_continuation_after_strict_m1_ready():
    zone = _buy_bplus_thesis_zone()
    analysis = _confirmed_buy_thesis_analysis(zone)
    snap = _snapshot(4270.70, spread_points=16.0)
    raw = (
        "ea_mode=WATCH_ONLY\n"
        "zone_state=ACTIVE\n"
        "setup_type=REVERSAL\n"
        "original_direction=BUY\n"
        "original_target1=4297.83000\n"
        "original_target2=4317.38000\n"
        "original_target3=4322.93000\n"
        "original_runner=0.00000\n"
        "flip_target1=4019.09000\n"
        "flip_target2=3995.91000\n"
        "flip_target3=0.00000\n"
        "flip_runner=0.00000\n"
    )

    out = _kv(guard_plan_text(raw, analysis, snap))

    assert out["ea_mode"] == "DUAL_BRANCH"
    assert out["core_handoff_ready"] == "1"
    assert out["execution_authority"] == "HTF_CORE_HANDOFF"
    assert out["thesis_continuation_bplus_override"] == "1"
    assert out["setup_type"] == "CONTINUATION"
    assert out["zone_setup_type_original"] == "REVERSAL"
    assert out["execution_role"] == "THESIS_CONTINUATION"
    assert out["execution_guard_reason"] == ""


def test_fresh_or_unconfirmed_bplus_zone_stays_watch_only():
    zone = _buy_bplus_thesis_zone()
    analysis = _analysis(zone)
    snap = _snapshot(4270.70, spread_points=16.0)
    raw = (
        "ea_mode=WATCH_ONLY\n"
        "zone_state=ACTIVE\n"
        "setup_type=REVERSAL\n"
        "original_direction=BUY\n"
        "original_target1=4297.83000\n"
        "original_target2=4317.38000\n"
        "original_target3=4322.93000\n"
    )

    out = _kv(guard_plan_text(raw, analysis, snap))

    assert out["ea_mode"] == "WATCH_ONLY"
    assert out["thesis_continuation_bplus_override"] == "0"
    assert out["core_handoff_ready"] == "0"


def test_confirmed_bplus_owner_still_fails_closed_without_ai_approval():
    zone = _buy_bplus_thesis_zone()
    analysis = _confirmed_buy_thesis_analysis(zone, ai_approved=False)
    snap = _snapshot(4270.70, spread_points=16.0)
    raw = (
        "ea_mode=WATCH_ONLY\n"
        "zone_state=ACTIVE\n"
        "setup_type=REVERSAL\n"
        "original_direction=BUY\n"
        "original_target1=4297.83000\n"
    )

    out = _kv(guard_plan_text(raw, analysis, snap))

    assert out["ea_mode"] == "WATCH_ONLY"
    assert out["thesis_continuation_bplus_override"] == "0"
    assert out["core_handoff_ready"] == "0"


def test_primary_observer_candidate_outside_core_is_context_false_and_wrong_targets_are_zeroed():
    zone = _sell_zone("ARMED")
    a = _analysis(zone)
    snap = _snapshot(4290.0)
    f = Feedback(
        ts=2,
        event="ML_CANDIDATE",
        analysis_id="A1",
        zone_id=zone.zone_id,
        price=4290.0,
        details={
            "direction": "SELL",
            "eligible": True,
            "entry_price": 4290.0,
            "target1": 4310.0,
            "target2": 4300.54,
            "target3": 4300.0,
            "rejection_reasons": [],
            "features": {"role": "PRIMARY", "zone_context": 1, "recent_zone_interaction": 1},
        },
    )
    out = normalize_candidate_feedback(f, a, snap)
    assert out.details["features"]["zone_context"] == 0
    assert out.details["features"]["recent_zone_interaction"] == 0
    assert "CORE_NOT_REACHED" in out.details["rejection_reasons"]
    assert "TARGET_DIRECTION_INVALID" in out.details["rejection_reasons"]
    assert out.details["eligible"] is False
    assert out.details["target1"] == 0.0
    assert out.details["target2"] == 0.0
    assert out.details["target3"] == 0.0


def test_reentry_does_not_require_return_to_original_core_but_still_requires_valid_targets():
    zone = _sell_zone("M1_READY")
    a = _analysis(zone)
    snap = _snapshot(4290.0)
    f = Feedback(
        ts=2,
        event="ML_CANDIDATE",
        analysis_id="A1",
        zone_id=zone.zone_id,
        price=4290.0,
        details={
            "direction": "SELL",
            "eligible": True,
            "entry_price": 4290.0,
            "target1": 4280.0,
            "target2": 4270.0,
            "target3": 4260.0,
            "rejection_reasons": [],
            "features": {"role": "REENTRY", "zone_context": 1, "recent_zone_interaction": 1},
        },
    )
    out = normalize_candidate_feedback(f, a, snap)
    assert "CORE_NOT_REACHED" not in out.details["rejection_reasons"]
    assert "TARGET_DIRECTION_INVALID" not in out.details["rejection_reasons"]
    assert out.details["eligible"] is True


def test_paper_ai_fallback_preserves_core_execution_handoff(monkeypatch):
    from app import execution_safety as safety

    monkeypatch.setattr(safety.SETTINGS, "paper_only", True)
    monkeypatch.setattr(safety.SETTINGS, "ai_enabled", True)
    monkeypatch.setattr(safety.SETTINGS, "require_ai_for_execution", True)
    zone = _sell_zone("M1_READY")
    zone.original_target1 = 4280.0
    zone.original_target2 = 4270.0
    zone.original_target3 = 4260.0
    a = _analysis(zone)
    a.ai_approved = False
    a.approved = True
    a.execution_policy = {
        "paper_ai_fallback": {"active": True, "authority": "HTF_CORE_HANDOFF"},
        "execution_window": {"mode": "CORE_NOW", "core_touched_at": 1234},
    }
    raw = (
        "ea_mode=WATCH_ONLY\n"
        "zone_state=ACTIVE\n"
        "original_direction=SELL\n"
        "original_target1=4280.00000\n"
        "original_target2=4270.00000\n"
        "original_target3=4260.00000\n"
    )
    out = _kv(guard_plan_text(raw, a, _snapshot(4306.5)))
    assert out["ea_mode"] == "DUAL_BRANCH"
    assert out["execution_authority"] == "HTF_CORE_HANDOFF"
    assert out["paper_ai_fallback_active"] == "1"
    assert out["execution_handoff_ts"] == "1234"


def test_paper_ai_fallback_preserves_zone_sweep_handoff(monkeypatch):
    from app import execution_safety as safety

    monkeypatch.setattr(safety.SETTINGS, "paper_only", True)
    monkeypatch.setattr(safety.SETTINGS, "ai_enabled", True)
    monkeypatch.setattr(safety.SETTINGS, "require_ai_for_execution", True)
    zone = _sell_zone("M1_READY")
    zone.original_target1 = 4280.0
    zone.original_target2 = 4270.0
    a = _analysis(zone)
    a.ai_approved = False
    a.approved = True
    a.execution_policy = {
        "paper_ai_fallback": {"active": True, "authority": "HTF_ZONE_SWEEP_HANDOFF"},
        "execution_window": {
            "active": True,
            "mode": "LATCHED_AFTER_ZONE_SWEEP",
            "sweep_confirmed": True,
            "sweep_ts": 2222,
        },
    }
    raw = (
        "ea_mode=WATCH_ONLY\n"
        "zone_state=ACTIVE\n"
        "original_direction=SELL\n"
        "original_target1=4280.00000\n"
        "original_target2=4270.00000\n"
    )
    out = _kv(guard_plan_text(raw, a, _snapshot(4290.0)))
    assert out["ea_mode"] == "DUAL_BRANCH"
    assert out["execution_authority"] == "HTF_ZONE_SWEEP_HANDOFF"
    assert out["zone_sweep_handoff_ready"] == "1"
    assert out["execution_handoff_ts"] == "2222"


def test_owner_target_progress_shifts_tp2_into_exported_target1():
    zone = _sell_zone("M1_READY")
    zone.original_target1 = 4351.33
    zone.original_target2 = 4341.13
    zone.original_target3 = 4319.88
    zone.core_low = 4392.19
    zone.core_high = 4398.19
    zone.zone_low = 4386.86
    zone.zone_high = 4407.49
    a = _analysis(zone)
    a.execution_policy = {
        "active_thesis": {
            "locked": True,
            "owner_zone_id": zone.zone_id,
            "direction": "SELL",
            "status": "OBJECTIVE_IN_PROGRESS",
            "target1_hit_at": 100,
            "target2_hit_at": 0,
            "target3_hit_at": 0,
            "best_price": 4348.0,
        },
        "execution_window": {"mode": "CORE_NOW", "core_touched_at": 200},
    }
    raw = (
        "ea_mode=DUAL_BRANCH\n"
        "zone_state=ACTIVE\n"
        "original_direction=SELL\n"
        "original_target1=4351.33000\n"
        "original_target2=4341.13000\n"
        "original_target3=4319.88000\n"
    )
    out = _kv(guard_plan_text(raw, a, _snapshot(4394.0, spread_points=16.0)))
    assert out["owner_target_progress_applied"] == "1"
    assert float(out["original_target1"]) == 4341.13
    assert float(out["original_target2"]) == 4319.88
    assert float(out["original_target3"]) == 0.0
    assert float(out["next_open_target"]) == 4341.13
