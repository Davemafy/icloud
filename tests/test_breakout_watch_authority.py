from app.execution_safety import guard_plan_text
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState


def test_continuation_breakout_watch_arms_without_zone_contact():
    snap = MarketSnapshot(sent_at=10000,bid=99.92,ask=100.08,spread_points=16,point=0.01,atr_h1=8,atr_m15=2)
    zone = Zone(
        zone_id="SELL_CONT", original_direction=Direction.SELL, flip_direction=Direction.BUY,
        setup_type="CONTINUATION", source_tf="H4>H1", grade=Grade.A, state=ZoneState.ACTIVE,
        core_low=118, core_high=120, core_method="ARMED|TEST", location_score=8,
        zone_low=118, zone_high=124, touch_count=0, independent_confluence_count=5,
        confluences=["LIQUIDITY_IN_MARKED_ZONE","BSL_IN_MARKED_ZONE"], source_ts=999,
        invalidation_level=124, invalidation_rule="M15 accepted invalidation",
        original_target1=96, original_target2=92, original_target3=88, clear_run=12,
    )
    analysis = Analysis(
        analysis_id="A_BREAKOUT", generated_at=10000, snapshot_at=10000,
        overall_bias=Direction.SELL, zones=[zone], selected_zone_id=zone.zone_id,
        approved=True, ai_approved=True,
        execution_policy={"multi_model":{"models":{"institutional_breakout":True},"regime":{"name":"RANGE","direction":"NEUTRAL"}}},
    )
    raw = "ea_mode=WATCH_ONLY\nzone_state=ACTIVE\nsetup_type=CONTINUATION\noriginal_direction=SELL\noriginal_target1=96.00000\noriginal_target2=92.00000\noriginal_target3=88.00000\n"
    kv = dict(line.split("=",1) for line in guard_plan_text(raw, analysis, snap).splitlines() if "=" in line)
    assert kv["ea_mode"] == "DUAL_BRANCH"
    assert kv["execution_authority"] == "STRUCTURAL_BREAKOUT_WATCH"
    assert kv["execution_role"] == "STRUCTURAL_BREAKOUT_WATCH"
    assert kv["core_handoff_ready"] == "0"
    assert kv["zone_contact_handoff_ready"] == "0"
    assert kv["core_required_for_authority"] == "0"
    assert "NO_EXECUTION_HANDOFF" not in kv["execution_guard_reason"]
