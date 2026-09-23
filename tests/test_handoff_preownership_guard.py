import pytest
from app import db
from app.execution_safety import has_live_directional_target
from app.liquidity_reversal_handoff import detect_liquidity_reversal_handoff
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.service import _acquire_final_ownership
from app.zone_reaction_lifecycle import register_analysis_zones


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "handoff_guard.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()


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


def test_sell_prezone_handoff_is_blocked_while_price_is_between_buy_and_sell_zones():
    sell = _sell_zone(target1=90.0)
    buy = Zone(
        zone_id="BUY_ORIGIN",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="REVERSAL",
        source_tf="H4>H1",
        grade=Grade.B_PLUS,
        state=ZoneState.ACTIVE,
        core_low=91.0,
        core_high=94.0,
        core_method="WATCH|TEST",
        location_score=7.0,
        zone_low=88.0,
        zone_high=95.0,
        touch_count=2,
        independent_confluence_count=3,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "SSL_IN_MARKED_ZONE"],
        source_ts=2,
        invalidation_level=88.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=118.0,
        clear_run=5.0,
    )
    analysis = _analysis(sell)
    analysis.zones = [sell, buy]
    register_analysis_zones(analysis)

    handoff = detect_liquidity_reversal_handoff(analysis, _snapshot(100.0))

    assert handoff["active"] is False
    assert handoff["authority"] == "NONE"
    assert handoff["reason"] == "INTERZONE_TRANSIT_REQUIRES_DESTINATION_ZONE_CONTACT"
    assert handoff["interzone_transit"]["origin_zone_id"] == "BUY_ORIGIN"
    assert handoff["interzone_transit"]["destination_zone_id"] == "SELL_REMOTE"
    assert handoff["requires_destination_zone_contact"] is True


def test_buy_prezone_handoff_is_blocked_while_price_is_between_sell_and_buy_zones():
    buy = Zone(
        zone_id="BUY_REMOTE",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=79.0,
        core_high=80.0,
        core_method="ARMED|TEST",
        location_score=9.0,
        zone_low=77.0,
        zone_high=82.0,
        touch_count=1,
        independent_confluence_count=4,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "SSL_IN_MARKED_ZONE"],
        source_ts=3,
        invalidation_level=77.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=110.0,
        clear_run=8.0,
    )
    sell = Zone(
        zone_id="SELL_ORIGIN",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="REVERSAL",
        source_tf="H4>H1",
        grade=Grade.B_PLUS,
        state=ZoneState.ACTIVE,
        core_low=106.0,
        core_high=109.0,
        core_method="WATCH|TEST",
        location_score=7.0,
        zone_low=105.0,
        zone_high=112.0,
        touch_count=2,
        independent_confluence_count=3,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "BSL_IN_MARKED_ZONE"],
        source_ts=4,
        invalidation_level=112.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=82.0,
        clear_run=5.0,
    )
    analysis = Analysis(
        analysis_id="A_BUY_TARGET_GUARD",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.BUY,
        zones=[buy, sell],
        selected_zone_id=buy.zone_id,
        approved=True,
        ai_approved=True,
    )
    register_analysis_zones(analysis)

    handoff = detect_liquidity_reversal_handoff(analysis, _snapshot(100.0))

    assert handoff["active"] is False
    assert handoff["authority"] == "NONE"
    assert handoff["reason"] == "INTERZONE_TRANSIT_REQUIRES_DESTINATION_ZONE_CONTACT"
    assert handoff["interzone_transit"]["origin_zone_id"] == "SELL_ORIGIN"
    assert handoff["interzone_transit"]["destination_zone_id"] == "BUY_REMOTE"


def test_sell_prezone_handoff_is_blocked_while_price_is_still_inside_lower_buy_zone():
    sell = _sell_zone(target1=90.0)
    # Mirrors the live failure shape: current price is inside the lower BUY
    # envelope, while the higher SELL envelope has not been reached yet.
    buy = Zone(
        zone_id="BUY_INTERACTING_ORIGIN",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="REVERSAL",
        source_tf="H4>H1",
        grade=Grade.B_PLUS,
        state=ZoneState.ACTIVE,
        core_low=99.0,
        core_high=101.0,
        core_method="INTERACTING|TEST",
        location_score=7.0,
        zone_low=96.0,
        zone_high=115.0,
        touch_count=11,
        independent_confluence_count=3,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "SSL_IN_MARKED_ZONE"],
        source_ts=20,
        invalidation_level=96.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=118.0,
        clear_run=5.0,
    )
    analysis = _analysis(sell)
    analysis.zones = [sell, buy]
    register_analysis_zones(analysis)

    handoff = detect_liquidity_reversal_handoff(analysis, _snapshot(100.0))

    assert handoff["active"] is False
    assert handoff["authority"] == "NONE"
    assert handoff["reason"] == "INTERZONE_TRANSIT_REQUIRES_DESTINATION_ZONE_CONTACT"
    transit = handoff["interzone_transit"]
    assert transit["origin_zone_id"] == buy.zone_id
    assert transit["destination_zone_id"] == sell.zone_id
    assert buy.zone_low <= transit["current_price"] <= buy.zone_high
    assert transit["current_price"] < sell.zone_low
