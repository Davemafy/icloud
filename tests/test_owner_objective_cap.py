from app import db
from app.execution_owner_mirror import owner_plan_text
from app.models import Analysis, Bar, Direction, Grade, Heartbeat, MarketSnapshot, Zone, ZoneState
from app.target_revalidation import target_ladder_truth
import app.thesis_ownership_policy as ownership
import app.scheduler as scheduler
from app.zone_reaction_lifecycle import register_analysis_zones, update_zone_reactions


def _zone(zone_id: str, direction: Direction, source_ts: int) -> Zone:
    if direction == Direction.BUY:
        return Zone(
            zone_id=zone_id,
            original_direction=direction,
            flip_direction=Direction.SELL,
            setup_type="CONTINUATION",
            source_tf="H1",
            grade=Grade.A,
            state=ZoneState.ACTIVE,
            core_low=99.0,
            core_high=101.0,
            core_method="M1_READY|TEST",
            location_score=8.0,
            zone_low=95.0,
            zone_high=105.0,
            source_ts=source_ts,
            invalidation_level=95.0,
            invalidation_rule="M15 accepted invalidation",
            original_target1=120.0,
            clear_run=19.0,
            confluences=["SSL_IN_MARKED_ZONE", "LIQUIDITY_IN_MARKED_ZONE"],
            independent_confluence_count=2,
        )
    return Zone(
        zone_id=zone_id,
        original_direction=direction,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H1",
        grade=Grade.A,
        state=ZoneState.ACTIVE,
        core_low=111.0,
        core_high=112.0,
        core_method="ARMED|TEST",
        location_score=8.0,
        zone_low=110.0,
        zone_high=115.0,
        source_ts=source_ts,
        invalidation_level=115.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=100.0,
        clear_run=11.0,
        confluences=["BSL_IN_MARKED_ZONE", "LIQUIDITY_IN_MARKED_ZONE"],
        independent_confluence_count=2,
    )


def _snapshot(ts: int = 10_000, mid: float = 105.0, bars=None) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=ts,
        bid=mid - 0.1,
        ask=mid + 0.1,
        spread_points=20.0,
        point=0.01,
        atr_m15=2.0,
        atr_h1=10.0,
        xau_m15=list(bars or []),
    )


def _seed_owner(
    tmp_path,
    monkeypatch,
    *,
    open_positions: int,
    best_price: float = 105.0,
    ownership_anchor: float = 100.0,
):
    path = tmp_path / "owner_cap.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    buy = _zone("BUY_OWNER", Direction.BUY, 111)
    sell = _zone("SELL_OPPOSING", Direction.SELL, 222)
    first = Analysis(
        analysis_id="A_OWNER",
        generated_at=9_000,
        snapshot_at=9_000,
        overall_bias=Direction.BUY,
        zones=[buy, sell],
        selected_zone_id=buy.zone_id,
        approved=True,
        ai_approved=True,
    )
    register_analysis_zones(first)
    key = "BUY|H1|111"
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE zone_reactions
            SET status='REACTION_CONFIRMED',
                core_touched_at=9000,
                reaction_confirmed_at=9100,
                ownership_acquired_at=9050,
                ownership_authority='HTF_CORE_HANDOFF',
                ownership_analysis_id=?,
                ownership_anchor_price=?,
                ownership_zone_id=?,
                ownership_zone_payload=?,
                best_price=?
            WHERE reaction_key=?
            """,
            (first.analysis_id, ownership_anchor, buy.zone_id, buy.model_dump_json(), best_price, key),
        )

    db.save_heartbeat(
        Heartbeat(
            ts=10_000,
            ea="InstitutionalSMC_SequenceEA",
            version="3.45",
            symbol="XAUUSD",
            details={"open_positions": open_positions, "restart_safe": open_positions == 0},
        )
    )
    return buy, sell, key


def _current(buy: Zone, sell: Zone) -> Analysis:
    return Analysis(
        analysis_id="A_CURRENT",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id=sell.zone_id,
    )


def test_flat_owner_gets_one_way_cap_in_front_of_new_opposing_primary(tmp_path, monkeypatch):
    buy, sell, key = _seed_owner(tmp_path, monkeypatch, open_positions=0)
    snap = _snapshot()
    analysis = _current(buy, sell)

    owner_zone = ownership.apply_thesis_ownership(analysis, snap)

    assert owner_zone is not None
    assert owner_zone.zone_id == buy.zone_id
    meta = analysis.execution_policy["active_thesis"]
    assert meta["ownership_objective_cap"] == 109.7
    assert meta["ownership_objective_cap_zone_id"] == sell.zone_id
    reconcile = analysis.execution_policy["owner_objective_cap_reconciliation"]
    assert reconcile["state"] == "APPLIED"
    assert reconcile["live_position_targets_mutated"] is False
    assert reconcile["frozen_deepest_target"] == 120.0

    truth = target_ladder_truth(analysis, owner_zone, snap)
    assert truth["open_targets"] == [109.7]
    assert truth["blocked_by_opposing_zone_cap"] == [120.0]
    assert truth["next_open_target"] == 109.7
    assert truth["frozen_owner_targets_preserved"] is True

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM zone_reactions WHERE reaction_key=?", (key,)).fetchone()
    assert float(row["ownership_objective_cap"]) == 109.7
    assert row["ownership_objective_cap_zone_id"] == sell.zone_id
    # Frozen lifecycle target and frozen owner payload remain unchanged for audit.
    assert float(row["target1"]) == 120.0
    frozen = Zone.model_validate_json(row["ownership_zone_payload"])
    assert frozen.original_target1 == 120.0

    mirror = owner_plan_text(10_000)
    assert "owner_mirror_target1=109.7\n" in mirror
    assert "owner_mirror_target2=0.0\n" in mirror
    assert "owner_mirror_best_price=0.0\n" in mirror


def test_flat_owner_cap_can_be_below_historical_anchor_when_still_ahead_of_current_market(tmp_path, monkeypatch):
    """Regression for the 29 Sep live state that exposed the v6.5.107 gap.

    Ownership was acquired around 4148.93, price later retraced to 4144.26, and a
    fresh SELL primary began at 4148.78. The canonical BUY front-run cap was
    4148.42: below the old ownership anchor, but safely above the current executable
    BUY quote. With zero positions this is a lifecycle destination, not a TP rewrite.
    """
    path = tmp_path / "live_65107_regression.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    buy = Zone(
        zone_id="PZ_H1_BUY_1790625600",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="CONTINUATION",
        source_tf="H1",
        grade=Grade.B_PLUS,
        state=ZoneState.ACTIVE,
        core_low=4111.28,
        core_high=4114.98,
        core_method="M1_READY|THESIS_CONTINUATION|REACTION_WINDOW",
        location_score=11.67,
        zone_low=4110.439,
        zone_high=4116.89,
        source_ts=1790625600,
        invalidation_level=4110.4385,
        invalidation_rule="M15 accepted invalidation",
        original_target1=4154.0395,
        clear_run=39.0595,
        confluences=["SSL_IN_MARKED_ZONE", "LIQUIDITY_IN_MARKED_ZONE"],
        independent_confluence_count=8,
    )
    sell = Zone(
        zone_id="PZ_H1_SELL_1790596800",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H1",
        grade=Grade.A,
        state=ZoneState.ACTIVE,
        core_low=4148.78,
        core_high=4154.40,
        core_method="ARMED|MASTER_SNIPER_SOURCE_EXACT",
        location_score=8.0,
        zone_low=4148.78,
        zone_high=4172.38,
        source_ts=1790596800,
        invalidation_level=4172.38,
        invalidation_rule="M15 accepted invalidation",
        original_target1=4140.67,
        original_target2=4118.77,
        confluences=["BSL_IN_MARKED_ZONE", "LIQUIDITY_IN_MARKED_ZONE"],
        independent_confluence_count=2,
    )
    first = Analysis(
        analysis_id="A_OWNER_LIVE",
        generated_at=1790665000,
        snapshot_at=1790665000,
        overall_bias=Direction.NEUTRAL,
        zones=[buy, sell],
        selected_zone_id=buy.zone_id,
        approved=True,
        ai_approved=True,
    )
    register_analysis_zones(first)
    key = "BUY|H1|1790625600"
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE zone_reactions
            SET status='REACTION_CONFIRMED',
                core_touched_at=1790642902,
                reaction_confirmed_at=1790643000,
                ownership_acquired_at=1790643000,
                ownership_authority='HTF_CORE_HANDOFF',
                ownership_analysis_id=?,
                ownership_anchor_price=4148.93,
                ownership_zone_id=?,
                ownership_zone_payload=?,
                best_price=4148.93
            WHERE reaction_key=?
            """,
            (first.analysis_id, buy.zone_id, buy.model_dump_json(), key),
        )

    now = 1790667744
    db.save_heartbeat(
        Heartbeat(
            ts=now,
            ea="InstitutionalSMC_SequenceEA",
            version="3.45",
            symbol="XAUUSD",
            details={"open_positions": 0, "restart_safe": True},
        )
    )
    snap = MarketSnapshot(
        sent_at=now,
        bid=4144.18,
        ask=4144.34,
        spread_points=16.0,
        point=0.01,
        atr_m15=7.2,
        atr_h1=20.0,
    )
    current = Analysis(
        analysis_id="A_1790667492_260b8707",
        generated_at=now,
        snapshot_at=now,
        overall_bias=Direction.NEUTRAL,
        zones=[sell, buy],
        selected_zone_id=sell.zone_id,
    )

    owner_zone = ownership.apply_thesis_ownership(current, snap)

    assert owner_zone is not None
    meta = current.execution_policy["active_thesis"]
    assert meta["ownership_anchor_price"] == 4148.93
    assert meta["ownership_objective_cap"] == 4148.42
    reconcile = current.execution_policy["owner_objective_cap_reconciliation"]
    assert reconcile["state"] == "APPLIED"
    assert reconcile["current_market_reference"] == 4144.34
    assert reconcile["cap_reference_basis"] == "CURRENT_FLAT_EXECUTABLE_QUOTE_NOT_HISTORICAL_OWNERSHIP_ANCHOR"

    truth = target_ladder_truth(current, owner_zone, snap)
    assert truth["next_open_target"] == 4148.42
    assert truth["blocked_by_opposing_zone_cap"] == [4154.0395]
    assert truth["history_reason"] == "TARGET_LIFECYCLE_OWNER_CAP_RECONCILED"

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM zone_reactions WHERE reaction_key=?", (key,)).fetchone()
    assert float(row["target1"]) == 4154.0395
    assert float(row["ownership_objective_cap"]) == 4148.42


def test_owner_cap_is_deferred_while_sequence_has_open_position(tmp_path, monkeypatch):
    buy, sell, key = _seed_owner(tmp_path, monkeypatch, open_positions=1)
    analysis = _current(buy, sell)

    ownership.apply_thesis_ownership(analysis, _snapshot())

    reconcile = analysis.execution_policy["owner_objective_cap_reconciliation"]
    assert reconcile["state"] == "DEFERRED_OPEN_POSITIONS"
    assert reconcile["candidate_cap"] == 109.7
    assert reconcile["live_position_targets_mutated"] is False
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ownership_objective_cap FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()
    assert float(row["ownership_objective_cap"] or 0.0) == 0.0


def test_cap_completion_uses_only_post_cap_evidence_not_historical_best(tmp_path, monkeypatch):
    buy, sell, key = _seed_owner(
        tmp_path,
        monkeypatch,
        open_positions=0,
        best_price=112.0,  # historical excursion before the new cap exists
    )
    set_snapshot = _snapshot(
        10_000,
        105.0,
        [Bar(ts=9_000, open=105.0, high=112.5, low=104.0, close=105.0)],
    )
    analysis = _current(buy, sell)
    owner_zone = ownership.apply_thesis_ownership(analysis, set_snapshot)
    assert owner_zone is not None

    truth = target_ladder_truth(analysis, owner_zone, set_snapshot)
    assert truth["next_open_target"] == 109.7
    assert truth["status"] == "ACTIVE_TARGETS_OPEN"

    # The only bar above the cap began before cap_set_at, so it cannot retroactively
    # complete a cap that did not yet exist.
    update_zone_reactions(set_snapshot)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT status,objective_complete_at,ownership_objective_cap_reached_at FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()
    assert row["status"] != "OBJECTIVE_COMPLETE"
    assert int(row["objective_complete_at"] or 0) == 0
    assert int(row["ownership_objective_cap_reached_at"] or 0) == 0

    crossed = _snapshot(
        10_900,
        110.0,
        [
            Bar(ts=10_000, open=105.0, high=110.2, low=104.8, close=109.9),
            Bar(ts=10_900, open=109.9, high=110.1, low=109.7, close=110.0),
        ],
    )
    update_zone_reactions(crossed)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT status,last_reason,objective_complete_at,ownership_objective_cap_reached_at FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()

    assert row["status"] == "OBJECTIVE_COMPLETE"
    assert row["last_reason"] == "OPPOSING_ZONE_OWNER_OBJECTIVE_CAP_REACHED"
    assert int(row["objective_complete_at"]) == 10_900
    assert int(row["ownership_objective_cap_reached_at"]) == 10_900


def test_scheduler_retries_missing_owner_cap_when_sequence_recovers_flat(monkeypatch):
    buy = _zone("BUY_OWNER", Direction.BUY, 111)
    sell = _zone("SELL_OPPOSING", Direction.SELL, 222)
    analysis = _current(buy, sell)
    analysis.selected_zone_id = buy.zone_id
    snap = _snapshot(ts=10_000, mid=105.0)

    owner = {
        "reaction_key": "BUY|H1|111",
        "ownership_zone_id": buy.zone_id,
        "latest_zone_id": buy.zone_id,
        "direction": "BUY",
        "ownership_objective_cap": 0.0,
    }
    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: analysis)
    monkeypatch.setattr(scheduler, "active_owner_snapshot", lambda now: owner)
    monkeypatch.setattr(scheduler, "_sequence_flat_fresh", lambda now: True)

    refresh = scheduler._owner_cap_reconciliation_refresh(snap, 10_000)

    assert refresh["owner_zone_id"] == buy.zone_id
    assert refresh["opposing_zone_id"] == sell.zone_id
    assert refresh["candidate_cap"] == 109.7
    assert "existing=0.00000" in refresh["signature"]

    owner["ownership_objective_cap"] = 109.7
    assert scheduler._owner_cap_reconciliation_refresh(snap, 10_001) == {}


def test_live_plan_retry_applies_deferred_flat_owner_cap_once_sequence_truth_is_fresh(tmp_path, monkeypatch):
    buy, sell, key = _seed_owner(tmp_path, monkeypatch, open_positions=0)
    snap = _snapshot(ts=10_100, mid=105.0)
    analysis = _current(buy, sell)

    # The seed heartbeat is now 100 seconds old, so the normal analysis-time
    # reconciliation must fail closed rather than trusting stale flatness.
    owner_zone = ownership.apply_thesis_ownership(analysis, snap)
    assert owner_zone is not None
    reconcile = analysis.execution_policy["owner_objective_cap_reconciliation"]
    assert reconcile["state"] == "DEFERRED_SEQUENCE_TRUTH_UNAVAILABLE"

    with db.connect() as conn:
        row = conn.execute(
            "SELECT ownership_objective_cap FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()
    assert float(row["ownership_objective_cap"] or 0.0) == 0.0

    # A fresh heartbeat arrives before the next full analysis cycle. The live-plan
    # retry must now apply the one-way cap immediately.
    db.save_heartbeat(
        Heartbeat(
            ts=10_100,
            ea="InstitutionalSMC_SequenceEA",
            version="3.67",
            symbol="XAUUSD",
            details={"open_positions": 0, "restart_safe": True},
        )
    )
    analysis.execution_policy["active_thesis"]["late_stage_reacquisition_required"] = True
    analysis.execution_policy["active_thesis"]["late_stage_reacquisition_satisfied"] = True
    ownership.reconcile_live_owner_objective_cap(analysis, snap)

    reconcile = analysis.execution_policy["owner_objective_cap_reconciliation"]
    assert reconcile["state"] == "APPLIED"
    assert reconcile["active_cap"] == 109.7
    assert analysis.execution_policy["active_thesis"]["ownership_objective_cap"] == 109.7
    assert analysis.execution_policy["active_thesis"]["late_stage_reacquisition_required"] is True
    assert analysis.execution_policy["active_thesis"]["late_stage_reacquisition_satisfied"] is True

    truth = target_ladder_truth(analysis, owner_zone, snap)
    assert truth["open_targets"] == [109.7]
    assert truth["blocked_by_opposing_zone_cap"] == [120.0]
    assert truth["history_reason"] == "TARGET_LIFECYCLE_OWNER_CAP_RECONCILED"
