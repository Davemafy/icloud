from app import db
from app.engine import active_plan_text
from app.models import Analysis, Bar, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.thesis_ownership_policy import acquire_execution_ownership, apply_thesis_ownership
from app.zone_reaction_lifecycle import register_analysis_zones, update_zone_reactions


def _kv(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def test_persisted_owner_plus_ai_outage_preserves_owner_but_final_safety_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_path", lambda: str(tmp_path / "pipeline.db"))
    db.init_db()

    snap = MarketSnapshot(
        sent_at=10_000,
        bid=99.92,
        ask=100.08,
        spread_points=16,
        point=0.01,
        atr_h1=8.0,
        atr_m15=2.0,
        xau_m15=[
            Bar(ts=9_100, open=100.4, high=101.2, low=99.4, close=100.2),
            Bar(ts=9_900, open=100.2, high=100.8, low=99.6, close=100.0),
        ],
    )
    zone = Zone(
        zone_id="SELL_OWNER",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=99.0,
        core_high=101.0,
        core_method="M1_READY|TEST_CORE_HANDOFF",
        location_score=9.0,
        zone_low=95.0,
        zone_high=106.0,
        touch_count=1,
        independent_confluence_count=6,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "BSL_IN_MARKED_ZONE"],
        source_ts=777,
        invalidation_level=106.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=90.0,
        original_target2=85.0,
        original_target3=80.0,
        clear_run=10.0,
    )
    analysis = Analysis(
        analysis_id="A_PIPELINE",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=False,
    )

    register_analysis_zones(analysis)
    update_zone_reactions(snap)
    owner = acquire_execution_ownership(
        analysis, snap, "HTF_CORE_HANDOFF", zone.zone_id, anchor_price=snap.mid
    )
    assert owner is not None

    owner_zone = apply_thesis_ownership(analysis, snap)
    assert owner_zone is not None
    owner_zone.core_method = "M1_READY|THESIS_CONTINUATION|TEST_CORE_HANDOFF"
    analysis.approved = True
    analysis.ai_approved = False
    policy = dict(analysis.execution_policy or {})
    policy["paper_ai_fallback"] = {
        "active": True,
        "reason": "AI_PROVIDER_UNAVAILABLE",
        "authority": "HTF_CORE_HANDOFF",
        "real_money_allowed": False,
    }
    policy["execution_window"] = {
        "active": True,
        "mode": "CORE_NOW",
        "core_now": True,
        "core_touched_at": snap.sent_at,
    }
    analysis.execution_policy = policy

    plan = _kv(active_plan_text(analysis, snap))
    # AI outage fallback preserves the paper thesis/owner, but the deliberately
    # incomplete and stale synthetic snapshot cannot pass the independent final
    # professional execution-separation gate.
    assert plan["ea_mode"] == "WATCH_ONLY"
    assert plan["execution_authority"] == "NONE"
    assert plan["paper_ai_fallback_active"] == "1"
    assert plan["owner_target_progress_applied"] == "1"
    assert float(plan["original_target1"]) == 90.0
    assert plan["live_target_direction_valid"] == "1"
    assert "ANALYSIS_HISTORY_WINDOW_INCOMPLETE" in plan["separation_guard"]
    assert "SNAPSHOT_SAFETY_HOLD" in plan["separation_guard"]
