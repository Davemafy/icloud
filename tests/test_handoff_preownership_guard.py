from app.execution_safety import has_live_directional_target
from app.liquidity_reversal_handoff import detect_liquidity_reversal_handoff
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.service import _acquire_final_ownership


def _snapshot(mid: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=10_000,
        bid=mid - 0.10,
        ask=mid + 0.10,
        spread_points=20.0,
        point=0.01,
        atr_h1=20.0,
        atr_m15=2.0,
    )


def _sell_zone(*, target1: float, target2: float = 0.0, target3: float = 0.0) -> Zone:
    return Zone(
        zone_id="SELL_REMOTE",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=120.0,
        core_high=121.0,
        core_method="ARMED|TEST",
        location_score=9.0,
        zone_low=118.0,
        zone_high=123.0,
        touch_count=1,
        independent_confluence_count=4,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "BSL_IN_MARKED_ZONE"],
        source_ts=1,
        invalidation_level=123.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=target1,
        original_target2=target2,
        original_target3=target3,
        clear_run=8.0,
    )


def _analysis(zone: Zone) -> Analysis:
    return Analysis(
        analysis_id="A_TARGET_GUARD",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )


def test_live_directional_target_requires_profit_side_of_current_market():
    snap = _snapshot(100.0)
    stale = _sell_zone(target1=110.0, target2=105.0, target3=101.0)
    live = _sell_zone(target1=110.0, target2=99.0, target3=90.0)

    assert has_live_directional_target(stale, snap) is False
    assert has_live_directional_target(live, snap) is True


def test_liquidity_reversal_detector_expires_when_all_sell_targets_already_traded():
    zone = _sell_zone(target1=110.0, target2=105.0, target3=101.0)
    handoff = detect_liquidity_reversal_handoff(_analysis(zone), _snapshot(100.0))

    assert handoff["active"] is False
    assert handoff["authority"] == "NONE"
    assert handoff["reason"] == "NO_LIVE_DIRECTIONAL_TARGET"


def test_final_ownership_guard_cannot_persist_stale_liquidity_handoff():
    zone = _sell_zone(target1=110.0, target2=105.0, target3=101.0)
    analysis = _analysis(zone)
    analysis.execution_policy = {
        "active_thesis": {"locked": False},
        "execution_authority": {
            "authority": "LIQUIDITY_REVERSAL_HANDOFF",
            "zone_id": zone.zone_id,
            "ownership_acquired": False,
        },
        "liquidity_reversal_handoff": {
            "active": True,
            "authority": "LIQUIDITY_REVERSAL_HANDOFF",
            "direction": "SELL",
            "context_zone_id": zone.zone_id,
            "liquidity_price": 110.0,
        },
        "paper_ai_fallback": {
            "active": True,
            "authority": "LIQUIDITY_REVERSAL_HANDOFF",
        },
    }

    authority, owner = _acquire_final_ownership(
        analysis,
        _snapshot(100.0),
        "LIQUIDITY_REVERSAL_HANDOFF",
        dict(analysis.execution_policy["liquidity_reversal_handoff"]),
    )

    assert authority == "NONE"
    assert owner is None
    assert analysis.execution_policy["execution_authority"]["authority"] == "NONE"
    assert analysis.execution_policy["execution_authority"]["block_reason"] == "NO_LIVE_DIRECTIONAL_TARGET"
    assert analysis.execution_policy["liquidity_reversal_handoff"]["active"] is False
    assert analysis.execution_policy["liquidity_reversal_handoff"]["reason"] == "NO_LIVE_DIRECTIONAL_TARGET"
    assert "paper_ai_fallback" not in analysis.execution_policy
    assert "LIQUIDITY_HANDOFF_NO_LIVE_DIRECTIONAL_TARGET" in analysis.guards
    assert analysis.ai_approved is False
    assert "expired before ownership" in analysis.trader_brief
