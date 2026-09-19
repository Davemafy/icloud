from app import db
import app.institutional_two_zone as zones
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.service import _acquire_final_ownership
from app.zone_reaction_lifecycle import register_analysis_zones


def _high_spread_snapshot(ts: int = 10_000) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=ts,
        bid=100.00,
        ask=100.59,
        spread_points=59,
        point=0.01,
        atr_h1=8.0,
        atr_m15=2.0,
    )


def _zone() -> Zone:
    return Zone(
        zone_id="SELL_HIGH_SPREAD",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=104.0,
        core_high=105.0,
        core_method="ARMED|TEST",
        location_score=9.0,
        zone_low=95.0,
        zone_high=106.0,
        touch_count=0,
        independent_confluence_count=5,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "BSL_IN_MARKED_ZONE"],
        source_ts=777,
        invalidation_level=106.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=90.0,
        original_target2=85.0,
        original_target3=80.0,
        clear_run=10.0,
    )


def test_high_spread_is_execution_hold_not_analysis_rejection(monkeypatch):
    snap = _high_spread_snapshot()
    zone = _zone()

    monkeypatch.setattr(zones, "prompt_snapshot_complete", lambda s: True)
    monkeypatch.setattr(zones, "liquidity_map", lambda s: [])
    monkeypatch.setattr(zones, "structure_bias", lambda bars: Direction.SELL)

    def install_map(analysis, snapshot):
        analysis.zones = [zone]
        analysis.selected_zone_id = zone.zone_id

    monkeypatch.setattr(zones, "apply_two_zone_institutional_map", install_map)

    analysis = zones.build_prompt_analysis(snap, generated_at=snap.sent_at)
    assert analysis.approved is True
    assert any(str(g).startswith("SPREAD_HIGH:59") for g in analysis.guards)
    assert analysis.selected_zone_id == zone.zone_id


def test_high_spread_does_not_prevent_persistent_handoff_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_path", lambda: str(tmp_path / "spread_owner.db"))
    db.init_db()

    snap = _high_spread_snapshot()
    zone = _zone()
    analysis = Analysis(
        analysis_id="A_HIGH_SPREAD",
        generated_at=snap.sent_at,
        snapshot_at=snap.sent_at,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
        execution_policy={
            "execution_authority": {
                "authority": "LIQUIDITY_REVERSAL_HANDOFF",
                "zone_id": zone.zone_id,
                "risk_multiplier": 0.5,
                "paper_only": True,
                "full_m1_sequence_required": True,
                "ownership_acquired": False,
            }
        },
    )
    register_analysis_zones(analysis)

    authority, owner = _acquire_final_ownership(
        analysis,
        snap,
        "LIQUIDITY_REVERSAL_HANDOFF",
        {"liquidity_price": 100.25},
    )
    assert authority == "LIQUIDITY_REVERSAL_HANDOFF"
    assert owner is not None
    assert owner["ownership_zone_id"] == zone.zone_id
    assert analysis.execution_policy["active_thesis"]["locked"] is True
