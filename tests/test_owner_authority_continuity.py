from app import service
from app.execution_safety import guard_plan_text, normalize_candidate_feedback
from app.models import Analysis, Direction, Feedback, Grade, MarketSnapshot, Zone, ZoneState


def _snapshot(mid: float = 4371.85) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=2_000,
        bid=mid - 0.09,
        ask=mid + 0.09,
        spread_points=18,
        point=0.01,
        atr_h1=20.0,
        atr_m15=4.0,
    )


def _zone() -> Zone:
    return Zone(
        zone_id="PZ_H4H1_SELL_11",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=4429.05,
        core_high=4435.05,
        core_method="ARMED|PROMPT_SWEEP_ROOM_GEOMETRY",
        location_score=9.0,
        zone_low=4414.05,
        zone_high=4440.05,
        touch_count=0,
        independent_confluence_count=11,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "BSL_IN_MARKED_ZONE"],
        source_ts=777,
        invalidation_level=4440.05,
        invalidation_rule="M15 accepted invalidation",
        original_target1=4351.33,
        original_target2=4341.13,
        original_target3=4320.18,
        clear_run=77.72,
    )


def _analysis() -> Analysis:
    zone = _zone()
    a = Analysis(
        analysis_id="A_OWNER_CONTINUITY",
        generated_at=2_000,
        snapshot_at=2_000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )
    a.execution_policy = {
        "active_thesis": {
            "locked": True,
            "direction": "SELL",
            "status": "REACTION_CONFIRMED",
            "owner_zone_id": zone.zone_id,
            "owner_zone_present": True,
            "ownership_authority": "LIQUIDITY_REVERSAL_HANDOFF",
            "ownership_acquired_at": 1_500,
            "reaction_confirmed_at": 1_480,
            "ownership_anchor_price": 4381.42,
            "source_tf": "H4>H1",
            "continuation_authority": True,
            "objective_open": True,
            "target1": 4351.33,
            "target2": 4341.13,
            "target3": 4320.18,
            "target1_hit_at": 0,
            "target2_hit_at": 0,
            "target3_hit_at": 0,
            "best_price": 4371.50,
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


def test_service_restores_live_owner_authority_without_new_location_handoff():
    a = _analysis()
    authority = service._stamp_execution_authority(a, None, {"active": False})
    meta = a.execution_policy["execution_authority"]

    assert authority == "LIQUIDITY_REVERSAL_HANDOFF"
    assert meta["zone_id"] == "PZ_H4H1_SELL_11"
    assert meta["owner_continuation"] is True
    assert meta["ownership_acquired"] is True
    assert meta["ownership_acquired_at"] == 1500


def test_existing_owner_does_not_get_reacquired_each_analysis(monkeypatch):
    a = _analysis()

    def should_not_run(*args, **kwargs):
        raise AssertionError("existing sticky owner must not be reacquired")

    monkeypatch.setattr(service, "acquire_execution_ownership", should_not_run)
    authority, owner = service._acquire_final_ownership(
        a,
        _snapshot(),
        "LIQUIDITY_REVERSAL_HANDOFF",
        {"active": False},
    )
    assert authority == "LIQUIDITY_REVERSAL_HANDOFF"
    assert owner is not None
    assert owner["owner_zone_id"] == "PZ_H4H1_SELL_11"


def test_plan_keeps_liquidity_reversal_owner_executable_far_from_remote_core():
    a = _analysis()
    service._stamp_execution_authority(a, None, {"active": False})
    raw = (
        "ea_mode=WATCH_ONLY\n"
        "zone_state=ACTIVE\n"
        "setup_type=CONTINUATION\n"
        "original_direction=SELL\n"
        "original_target1=4351.33000\n"
        "original_target2=4341.13000\n"
        "original_target3=4320.18000\n"
        "original_runner=0.00000\n"
    )
    out = _kv(guard_plan_text(raw, a, _snapshot()))

    assert out["ea_mode"] == "DUAL_BRANCH"
    assert out["execution_authority"] == "LIQUIDITY_REVERSAL_HANDOFF"
    assert out["owner_continuation_ready"] == "1"
    assert out["owner_continuation_authority"] == "LIQUIDITY_REVERSAL_HANDOFF"
    assert out["execution_role"] == "THESIS_CONTINUATION"
    assert out["execution_handoff_ts"] == "1480"
    assert out["liquidity_reversal_direction"] == "SELL"
    assert out["liquidity_reversal_label"] == "PERSISTED_THESIS_OWNER"
    assert out["liquidity_reversal_price"] == "4381.42000"
    assert out["core_required_for_authority"] == "0"
    assert out["live_target_direction_valid"] == "1"


def test_observer_does_not_reject_sticky_owner_for_core_not_reached():
    a = _analysis()
    service._stamp_execution_authority(a, None, {"active": False})
    snap = _snapshot()
    feedback = Feedback(
        ts=2_001,
        event="ML_CANDIDATE",
        analysis_id=a.analysis_id,
        zone_id="PZ_H4H1_SELL_11",
        price=4371.85,
        details={
            "direction": "SELL",
            "eligible": True,
            "entry_price": 4371.85,
            "target1": 4351.33,
            "target2": 4341.13,
            "target3": 4320.18,
            "rejection_reasons": [],
            "features": {"role": "PRIMARY", "zone_context": 0, "recent_zone_interaction": 0},
        },
    )
    out = normalize_candidate_feedback(feedback, a, snap)
    reasons = out.details["rejection_reasons"]
    features = out.details["features"]

    assert "CORE_NOT_REACHED" not in reasons
    assert features["owner_continuation"] == 1
    assert features["owner_continuation_authority"] == "LIQUIDITY_REVERSAL_HANDOFF"
    assert features["interaction_basis"] == "PERSISTED_THESIS_OWNER"
    assert features["zone_context"] == 1
