from app import db
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
import app.thesis_ownership_policy as ownership
from app.zone_reaction_lifecycle import register_analysis_zones


def test_structural_breakout_handoff_acquires_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_path", lambda: str(tmp_path / "breakout_owner.db"))
    db.init_db()
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
    )
    register_analysis_zones(analysis)
    owner = ownership.acquire_execution_ownership(
        analysis, snap, "STRUCTURAL_BREAKOUT_HANDOFF", zone.zone_id, anchor_price=100.0
    )
    assert owner is not None
    assert owner["ownership_authority"] == "STRUCTURAL_BREAKOUT_HANDOFF"
    assert owner["status"] == "REACTION_CONFIRMED"
    assert float(owner["ownership_anchor_price"]) == 100.0
