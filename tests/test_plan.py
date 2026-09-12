from app.engine import active_plan_text
from app.models import Analysis, Direction, Zone, ZoneState, Grade


def test_plan_exports_dual_branch_and_flip_targets():
    z=Zone(zone_id="Z1",original_direction=Direction.SELL,flip_direction=Direction.BUY,setup_type="CONTINUATION",source_tf="D1>H4>H1",grade=Grade.A,state=ZoneState.ACTIVE,core_low=100,core_high=101,core_method="STRICT",location_score=9,zone_low=99,zone_high=103,invalidation_level=103,invalidation_rule="x",original_target1=95,flip_target1=108)
    a=Analysis(analysis_id="A1",generated_at=1,snapshot_at=1,overall_bias=Direction.SELL,zones=[z],selected_zone_id="Z1",approved=True,ai_approved=True)
    t=active_plan_text(a)
    assert "original_direction=SELL" in t
    assert "flip_direction=BUY" in t
    assert "flip_target1=108.00000" in t
    assert "flip_invalidation_is_not_entry=1" in t
