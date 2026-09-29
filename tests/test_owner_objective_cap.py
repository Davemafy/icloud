from app import db
from app.execution_owner_mirror import owner_plan_text
from app.models import Analysis, Bar, Direction, Grade, Heartbeat, MarketSnapshot, Zone, ZoneState
from app.target_revalidation import target_ladder_truth
import app.thesis_ownership_policy as ownership
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


def _seed_owner(tmp_path, monkeypatch, *, open_positions: int, best_price: float = 105.0):
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
                ownership_anchor_price=100.0,
                ownership_zone_id=?,
                ownership_zone_payload=?,
                best_price=?
            WHERE reaction_key=?
            """,
            (first.analysis_id, buy.zone_id, buy.model_dump_json(), best_price, key),
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
