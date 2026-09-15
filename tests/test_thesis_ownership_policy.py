from app import db
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
import app.thesis_ownership_policy as policy
from app.zone_reaction_lifecycle import register_analysis_zones, update_zone_reactions


def _snapshot(mid: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=10_000,
        bid=mid - 0.1,
        ask=mid + 0.1,
        spread_points=20.0,
        point=0.01,
        atr_m15=2.0,
    )


def _zone(zone_id: str, direction: Direction, source_ts: int, grade: Grade) -> Zone:
    required = "SSL_IN_MARKED_ZONE" if direction == Direction.BUY else "BSL_IN_MARKED_ZONE"
    return Zone(
        zone_id=zone_id,
        original_direction=direction,
        flip_direction=direction.opposite(),
        setup_type="REVERSAL" if direction == Direction.BUY else "CONTINUATION",
        source_tf="H4>H1" if direction == Direction.BUY else "H1",
        grade=grade,
        state=ZoneState.ACTIVE,
        core_low=99.0,
        core_high=101.0,
        core_method="WATCH|TEST",
        location_score=8.0,
        zone_low=95.0,
        zone_high=105.0,
        touch_count=2 if grade == Grade.B_PLUS else 1,
        independent_confluence_count=4,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", required, "INSTITUTIONAL_DISPLACEMENT"],
        source_ts=source_ts,
        invalidation_level=95.0 if direction == Direction.BUY else 105.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=110.0 if direction == Direction.BUY else 90.0,
        clear_run=8.0,
    )


def _owner() -> dict:
    return {
        "reaction_key": "BUY|H4>H1|111",
        "latest_zone_id": "BUY_ZONE",
        "direction": "BUY",
        "source_tf": "H4>H1",
        "source_ts": 111,
        "status": "REACTION_CONFIRMED",
        "grade": "B+",
        "core_touched_at": 9000,
        "reaction_confirmed_at": 9100,
        "target1": 110.0,
        "target2": 120.0,
        "target3": 130.0,
        "objective_complete_at": 0,
        "invalidated_at": 0,
        "best_price": 104.0,
        "mfe_price": 3.0,
    }


def test_live_buy_thesis_overrides_new_sell_ranking(monkeypatch):
    buy = _zone("BUY_ZONE", Direction.BUY, 111, Grade.B_PLUS)
    sell = _zone("SELL_ZONE", Direction.SELL, 222, Grade.A)
    analysis = Analysis(
        analysis_id="A1",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id="SELL_ZONE",
    )
    monkeypatch.setattr(policy, "_active_owner_row", lambda now: _owner())

    owner = policy.apply_thesis_ownership(analysis, _snapshot())

    assert owner is buy
    assert analysis.selected_zone_id == "BUY_ZONE"
    meta = analysis.execution_policy["active_thesis"]
    assert meta["locked"] is True
    assert meta["direction"] == "BUY"
    assert meta["opposite_execution_blocked"] is True
    assert meta["continuation_authority"] is True
    assert "thesis_owner:BUY:REACTION_CONFIRMED" in buy.notes


def test_live_thesis_without_current_owner_zone_fails_closed(monkeypatch):
    sell = _zone("SELL_ZONE", Direction.SELL, 222, Grade.A)
    analysis = Analysis(
        analysis_id="A1",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell],
        selected_zone_id="SELL_ZONE",
    )
    monkeypatch.setattr(policy, "_active_owner_row", lambda now: _owner())

    owner = policy.apply_thesis_ownership(analysis, _snapshot())

    assert owner is None
    assert analysis.selected_zone_id == ""
    assert "ACTIVE_THESIS_OWNER_NOT_IN_CURRENT_MAP" in analysis.guards
    assert analysis.execution_policy["active_thesis"]["opposite_execution_blocked"] is True


def test_no_live_thesis_leaves_normal_selection_unchanged(monkeypatch):
    sell = _zone("SELL_ZONE", Direction.SELL, 222, Grade.A)
    analysis = Analysis(
        analysis_id="A1",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell],
        selected_zone_id="SELL_ZONE",
    )
    monkeypatch.setattr(policy, "_active_owner_row", lambda now: None)

    owner = policy.apply_thesis_ownership(analysis, _snapshot())

    assert owner is None
    assert analysis.selected_zone_id == "SELL_ZONE"
    assert analysis.execution_policy["active_thesis"]["locked"] is False


def test_current_snapshot_interaction_locks_owner_before_opposite_selection(tmp_path, monkeypatch):
    """Regression for v6.5.9 startup ordering: lifecycle must be current before ownership."""
    path = tmp_path / "thesis_sync.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    buy = _zone("BUY_ZONE", Direction.BUY, 111, Grade.B_PLUS)
    sell = _zone("SELL_ZONE", Direction.SELL, 222, Grade.A_PLUS)
    # Keep the new SELL map far away while current price is inside the BUY core.
    sell.core_low = 120.0
    sell.core_high = 121.0
    sell.zone_low = 118.0
    sell.zone_high = 123.0

    analysis = Analysis(
        analysis_id="A_SYNC",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id="SELL_ZONE",
    )
    snap = _snapshot(100.0)

    register_analysis_zones(analysis)
    update_zone_reactions(snap)
    owner = policy.apply_thesis_ownership(analysis, snap)

    assert owner is buy
    assert analysis.selected_zone_id == "BUY_ZONE"
    meta = analysis.execution_policy["active_thesis"]
    assert meta["locked"] is True
    assert meta["direction"] == "BUY"
    assert meta["status"] == "INTERACTING"
    assert meta["opposite_execution_blocked"] is True
