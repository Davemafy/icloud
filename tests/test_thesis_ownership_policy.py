from app import db
from app.models import Analysis, Direction, Grade, Heartbeat, MarketSnapshot, Zone, ZoneState
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
        "grade": "A",
        "core_low": 99.0,
        "core_high": 101.0,
        "zone_low": 95.0,
        "zone_high": 105.0,
        "core_touched_at": 9000,
        "reaction_confirmed_at": 9100,
        "target1": 110.0,
        "target2": 120.0,
        "target3": 130.0,
        "objective_complete_at": 0,
        "invalidated_at": 0,
        "best_price": 104.0,
        "mfe_price": 3.0,
        "ownership_acquired_at": 9050,
        "ownership_authority": "HTF_CORE_HANDOFF",
        "ownership_analysis_id": "A0",
        "ownership_anchor_price": 100.0,
    }


def test_live_buy_thesis_overrides_new_sell_ranking(monkeypatch):
    buy = _zone("BUY_ZONE", Direction.BUY, 111, Grade.A)
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
    assert meta["ownership_authority"] == "HTF_CORE_HANDOFF"
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
    assert analysis.execution_policy["active_thesis"]["interaction_alone_never_locks"] is True


def test_watch_interaction_does_not_lock_opposite_side_before_execution_handoff(tmp_path, monkeypatch):
    """A B+/multi-touch WATCH interaction is lifecycle evidence, not execution ownership."""
    path = tmp_path / "thesis_sync.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    buy = _zone("BUY_ZONE", Direction.BUY, 111, Grade.B_PLUS)
    sell = _zone("SELL_ZONE", Direction.SELL, 222, Grade.A_PLUS)
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

    assert owner is None
    assert analysis.selected_zone_id == "SELL_ZONE"
    meta = analysis.execution_policy["active_thesis"]
    assert meta["locked"] is False
    assert policy.active_owner_snapshot(snap.sent_at) is None


def test_htf_core_handoff_acquires_persistent_owner_then_blocks_opposite_ranking(tmp_path, monkeypatch):
    path = tmp_path / "thesis_acquire.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    buy = _zone("BUY_ZONE", Direction.BUY, 111, Grade.A_PLUS)
    sell = _zone("SELL_ZONE", Direction.SELL, 222, Grade.A_PLUS)
    sell.core_low = 120.0
    sell.core_high = 121.0
    sell.zone_low = 118.0
    sell.zone_high = 123.0
    snap = _snapshot(100.0)
    first = Analysis(
        analysis_id="A_HANDOFF",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.BUY,
        zones=[buy, sell],
        selected_zone_id="BUY_ZONE",
        approved=True,
        ai_approved=True,
    )

    register_analysis_zones(first)
    update_zone_reactions(snap)
    assert policy.active_owner_snapshot(snap.sent_at) is None

    acquired = policy.acquire_execution_ownership(
        first, snap, "HTF_CORE_HANDOFF", "BUY_ZONE", anchor_price=100.0
    )
    assert acquired is not None
    assert acquired["ownership_authority"] == "HTF_CORE_HANDOFF"
    assert int(acquired["ownership_acquired_at"]) == snap.sent_at

    next_analysis = Analysis(
        analysis_id="A_NEXT",
        generated_at=10_001,
        snapshot_at=10_001,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id="SELL_ZONE",
    )
    owner_zone = policy.apply_thesis_ownership(next_analysis, snap)
    assert owner_zone is not None
    assert owner_zone.zone_id == buy.zone_id
    assert owner_zone.core_low == buy.core_low
    assert owner_zone.core_high == buy.core_high
    assert next_analysis.selected_zone_id == "BUY_ZONE"
    assert next_analysis.execution_policy["active_thesis"]["locked"] is True


def test_liquidity_reversal_handoff_can_acquire_owner_without_touching_remote_core(tmp_path, monkeypatch):
    path = tmp_path / "liq_owner.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    sell = _zone("SELL_ZONE", Direction.SELL, 222, Grade.A_PLUS)
    sell.core_low = 120.0
    sell.core_high = 121.0
    sell.zone_low = 118.0
    sell.zone_high = 123.0
    sell.original_target1 = 90.0
    snap = _snapshot(100.0)
    analysis = Analysis(
        analysis_id="A_LIQ",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell],
        selected_zone_id="SELL_ZONE",
        approved=True,
    )
    register_analysis_zones(analysis)

    acquired = policy.acquire_execution_ownership(
        analysis, snap, "LIQUIDITY_REVERSAL_HANDOFF", "SELL_ZONE", anchor_price=110.0
    )
    assert acquired is not None
    assert acquired["status"] == "REACTION_CONFIRMED"
    assert int(acquired["core_touched_at"] or 0) == 0
    assert acquired["ownership_authority"] == "LIQUIDITY_REVERSAL_HANDOFF"
    assert float(acquired["ownership_anchor_price"]) == 110.0
    assert policy.active_owner_snapshot(snap.sent_at) is not None
    assert "Execution ownership acquired by" not in analysis.trader_brief


def test_confirmed_owner_has_separate_broad_and_strict_core_buffers(monkeypatch):
    """Broad refresh must not consume the later strict M1 handoff edge."""
    monkeypatch.setattr(policy, "active_owner_snapshot", lambda now: _owner())

    broad_only = _snapshot(101.45)
    assert policy.owner_core_interacting(broad_only) is not None
    assert policy.owner_m1_handoff_interacting(broad_only) is None

    strict = _snapshot(101.15)
    assert policy.owner_m1_handoff_interacting(strict) is not None


def test_m1_handoff_requires_confirmed_or_in_progress_owner(monkeypatch):
    owner = _owner()
    owner["status"] = "INTERACTING"
    monkeypatch.setattr(policy, "active_owner_snapshot", lambda now: owner)

    assert policy.owner_core_interacting(_snapshot(100.0)) is not None
    assert policy.owner_m1_handoff_interacting(_snapshot(100.0)) is None



def _seed_legacy_bplus_owner(tmp_path, monkeypatch, *, heartbeat_ts: int | None, open_positions: int = 0):
    path = tmp_path / "legacy_bplus_owner.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    zone = _zone("BUY_LEGACY", Direction.BUY, 333, Grade.B_PLUS)
    analysis = Analysis(
        analysis_id="A_LEGACY",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )
    register_analysis_zones(analysis)
    key = "BUY|H4>H1|333"
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE zone_reactions
            SET status='OBJECTIVE_IN_PROGRESS',
                core_touched_at=9000,
                reaction_confirmed_at=9050,
                ownership_acquired_at=9060,
                ownership_authority='HTF_CORE_HANDOFF',
                ownership_analysis_id='A_PRE_V2',
                ownership_anchor_price=100.0,
                ownership_zone_id=?,
                ownership_zone_payload=?,
                last_reason='LEGACY_BPLUS_OWNER'
            WHERE reaction_key=?
            """,
            (zone.zone_id, zone.model_dump_json(), key),
        )

    if heartbeat_ts is not None:
        db.save_heartbeat(
            Heartbeat(
                ts=heartbeat_ts,
                ea="InstitutionalSMC_SequenceEA",
                version="3.38",
                symbol="XAUUSD",
                details={
                    "open_positions": open_positions,
                    "restart_safe": open_positions == 0,
                },
            )
        )
    return key, zone


def test_flat_legacy_bplus_owner_is_retired_with_fresh_sequence_truth(tmp_path, monkeypatch):
    key, _ = _seed_legacy_bplus_owner(
        tmp_path,
        monkeypatch,
        heartbeat_ts=10_000,
        open_positions=0,
    )

    assert policy.active_owner_snapshot(10_000) is None

    with db.connect() as conn:
        row = conn.execute(
            "SELECT ownership_acquired_at,status,last_reason FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()
    assert int(row["ownership_acquired_at"] or 0) == 0
    assert row["status"] == "OBJECTIVE_IN_PROGRESS"
    assert policy.LEGACY_OWNER_RELEASE_REASON in str(row["last_reason"])


def test_legacy_bplus_owner_stays_locked_while_sequence_has_open_positions(tmp_path, monkeypatch):
    key, _ = _seed_legacy_bplus_owner(
        tmp_path,
        monkeypatch,
        heartbeat_ts=10_000,
        open_positions=1,
    )

    owner = policy.active_owner_snapshot(10_000)

    assert owner is not None
    assert owner["reaction_key"] == key
    assert owner["compat_execution_lock_protected"] is True
    assert owner["compat_execution_lock_reason"] == "SEQUENCE_POSITIONS_OPEN"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ownership_acquired_at FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()
    assert int(row["ownership_acquired_at"] or 0) == 9060


def test_legacy_bplus_owner_fails_closed_when_sequence_truth_is_stale(tmp_path, monkeypatch):
    key, _ = _seed_legacy_bplus_owner(
        tmp_path,
        monkeypatch,
        heartbeat_ts=9_900,
        open_positions=0,
    )

    owner = policy.active_owner_snapshot(10_000)

    assert owner is not None
    assert owner["reaction_key"] == key
    assert owner["compat_execution_lock_protected"] is True
    assert owner["compat_execution_lock_reason"] == "SEQUENCE_POSITION_TRUTH_UNAVAILABLE"


def test_bplus_cannot_acquire_new_execution_ownership_directly(tmp_path, monkeypatch):
    path = tmp_path / "bplus_direct_acquire.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    zone = _zone("BUY_BPLUS", Direction.BUY, 444, Grade.B_PLUS)
    analysis = Analysis(
        analysis_id="A_BPLUS",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.BUY,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )
    register_analysis_zones(analysis)

    acquired = policy.acquire_execution_ownership(
        analysis,
        _snapshot(),
        "HTF_CORE_HANDOFF",
        zone.zone_id,
        anchor_price=100.0,
    )

    assert acquired is None
    assert policy.active_owner_snapshot(10_000) is None


def _seed_interzone_liquidity_owner(tmp_path, monkeypatch, *, open_positions: int):
    path = tmp_path / "interzone_liquidity_owner.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    sell = _zone("SELL_REMOTE", Direction.SELL, 555, Grade.A_PLUS)
    sell.core_low = 120.0
    sell.core_high = 121.0
    sell.zone_low = 118.0
    sell.zone_high = 123.0
    sell.original_target1 = 110.0
    sell.original_target2 = 105.0
    sell.original_target3 = 90.0

    buy = _zone("BUY_ORIGIN", Direction.BUY, 556, Grade.B_PLUS)
    buy.core_low = 91.0
    buy.core_high = 94.0
    buy.zone_low = 88.0
    buy.zone_high = 95.0
    buy.original_target1 = 118.0

    first = Analysis(
        analysis_id="A_INTERZONE_OWNER",
        generated_at=10_000,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id=sell.zone_id,
        approved=True,
        ai_approved=True,
    )
    snap = _snapshot(100.0)
    register_analysis_zones(first)
    acquired = policy.acquire_execution_ownership(
        first,
        snap,
        "LIQUIDITY_REVERSAL_HANDOFF",
        sell.zone_id,
        anchor_price=110.0,
    )
    assert acquired is not None

    db.save_heartbeat(
        Heartbeat(
            ts=10_000,
            ea="InstitutionalSMC_SequenceEA",
            version="3.38",
            symbol="XAUUSD",
            details={
                "open_positions": open_positions,
                "restart_safe": open_positions == 0,
            },
        )
    )
    return snap, sell, buy, str(acquired["reaction_key"])


def test_flat_prezone_liquidity_owner_releases_during_interzone_transit(tmp_path, monkeypatch):
    snap, sell, buy, key = _seed_interzone_liquidity_owner(
        tmp_path,
        monkeypatch,
        open_positions=0,
    )
    current = Analysis(
        analysis_id="A_INTERZONE_CURRENT",
        generated_at=10_001,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id=sell.zone_id,
    )

    owner_zone = policy.apply_thesis_ownership(current, snap)

    assert owner_zone is None
    assert current.selected_zone_id == sell.zone_id
    assert current.execution_policy["active_thesis"]["locked"] is False
    release = current.execution_policy["interzone_owner_release"]
    assert release["released"] is True
    assert release["reason"] == policy.INTERZONE_OWNER_RELEASE_REASON
    assert release["interzone_transit"]["origin_zone_id"] == buy.zone_id
    assert release["interzone_transit"]["destination_zone_id"] == sell.zone_id

    with db.connect() as conn:
        row = conn.execute(
            "SELECT ownership_acquired_at,last_reason FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()
    assert int(row["ownership_acquired_at"] or 0) == 0
    assert policy.INTERZONE_OWNER_RELEASE_REASON in str(row["last_reason"])


def test_prezone_liquidity_owner_stays_fail_closed_with_open_positions(tmp_path, monkeypatch):
    snap, sell, buy, key = _seed_interzone_liquidity_owner(
        tmp_path,
        monkeypatch,
        open_positions=1,
    )
    current = Analysis(
        analysis_id="A_INTERZONE_OPEN_POSITION",
        generated_at=10_001,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id=sell.zone_id,
    )

    owner_zone = policy.apply_thesis_ownership(current, snap)

    assert owner_zone is not None
    assert owner_zone.zone_id == sell.zone_id
    assert current.execution_policy["active_thesis"]["locked"] is True
    assert "interzone_owner_release" not in current.execution_policy
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ownership_acquired_at FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()
    assert int(row["ownership_acquired_at"] or 0) == 10_000


def test_flat_prezone_owner_releases_while_price_is_inside_lower_buy_origin(tmp_path, monkeypatch):
    snap, sell, buy, key = _seed_interzone_liquidity_owner(
        tmp_path,
        monkeypatch,
        open_positions=0,
    )
    # Move the lower BUY envelope up around current price to reproduce the live
    # v6.5.55 condition: BUY is INTERACTING and SELL remains above market.
    buy.zone_low = 96.0
    buy.zone_high = 115.0
    buy.core_low = 99.0
    buy.core_high = 101.0
    buy.core_method = "INTERACTING|TEST"

    current = Analysis(
        analysis_id="A_INTERZONE_INSIDE_ORIGIN",
        generated_at=10_001,
        snapshot_at=10_000,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id=sell.zone_id,
    )

    owner_zone = policy.apply_thesis_ownership(current, snap)

    assert owner_zone is None
    assert current.execution_policy["active_thesis"]["locked"] is False
    release = current.execution_policy["interzone_owner_release"]
    assert release["released"] is True
    assert release["interzone_transit"]["origin_zone_id"] == buy.zone_id
    assert release["interzone_transit"]["destination_zone_id"] == sell.zone_id
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ownership_acquired_at,last_reason FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()
    assert int(row["ownership_acquired_at"] or 0) == 0
    assert policy.INTERZONE_OWNER_RELEASE_REASON in str(row["last_reason"])
