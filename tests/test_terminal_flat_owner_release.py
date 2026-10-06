from app import db
from app.models import Analysis, Direction, Grade, Heartbeat, MarketSnapshot, Zone, ZoneState
import app.thesis_ownership_policy as policy
from app.zone_reaction_lifecycle import register_analysis_zones, update_zone_reactions


def _snapshot(ts: int = 10_000, mid: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=ts,
        bid=mid - 0.1,
        ask=mid + 0.1,
        spread_points=20.0,
        point=0.01,
        atr_m15=2.0,
    )


def _zone() -> Zone:
    return Zone(
        zone_id="BUY_TERM",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="REVERSAL",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=99.0,
        core_high=101.0,
        core_method="M1_READY|TEST",
        location_score=10.0,
        zone_low=95.0,
        zone_high=105.0,
        touch_count=1,
        independent_confluence_count=4,
        confluences=[
            "LIQUIDITY_IN_MARKED_ZONE",
            "SSL_IN_MARKED_ZONE",
            "INSTITUTIONAL_DISPLACEMENT",
        ],
        source_ts=111,
        invalidation_level=95.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=110.0,
        clear_run=8.0,
    )


def _seed_owner(tmp_path, monkeypatch):
    path = tmp_path / "terminal_flat_owner.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()
    snap = _snapshot()
    zone = _zone()
    analysis = Analysis(
        analysis_id="A_TERM",
        generated_at=snap.sent_at,
        snapshot_at=snap.sent_at,
        overall_bias=Direction.BUY,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )
    register_analysis_zones(analysis)
    update_zone_reactions(snap)
    owner = policy.acquire_execution_ownership(
        analysis, snap, "HTF_CORE_HANDOFF", zone.zone_id, anchor_price=100.0
    )
    assert owner is not None
    key = str(owner["reaction_key"])
    campaign = (
        f"{owner['direction']}|{owner['source_tf']}|{int(owner['source_ts'])}|"
        f"{int(owner['ownership_acquired_at'])}"
    )
    return snap, zone, analysis, key, campaign


def _heartbeat(ts: int, campaign: str, *, open_positions: int, terminal: bool):
    details = {
        "open_positions": open_positions,
        "restart_safe": open_positions == 0,
        "primary_entries": 1,
        "reentries": 2 if terminal else 1,
        "campaign_key": campaign,
        "opportunity_slot": "REENTRY_CAP_REACHED" if terminal else "R2",
        "gate_stage": "THESIS" if terminal else "M1_SWEEP",
        "gate_reason": "REENTRY_LIMIT_REACHED" if terminal else "WAITING_FOR_VALID_M1_SWEEP",
    }
    db.save_heartbeat(
        Heartbeat(
            ts=ts,
            ea="InstitutionalSMC_SequenceEA",
            version="3.72",
            symbol="XAUUSD",
            details=details,
        )
    )


def test_terminal_flat_exact_campaign_releases_execution_lock_but_not_objective(tmp_path, monkeypatch):
    snap, _, _, key, campaign = _seed_owner(tmp_path, monkeypatch)
    _heartbeat(snap.sent_at, campaign, open_positions=0, terminal=True)

    assert policy.active_owner_snapshot(snap.sent_at) is None

    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT ownership_acquired_at,ownership_execution_released_at,
                   ownership_execution_release_reason,objective_complete_at,
                   invalidated_at,status
            FROM zone_reactions WHERE reaction_key=?
            """,
            (key,),
        ).fetchone()
    assert int(row["ownership_acquired_at"] or 0) == snap.sent_at
    assert int(row["ownership_execution_released_at"] or 0) == snap.sent_at
    assert row["ownership_execution_release_reason"] == policy.TERMINAL_FLAT_OWNER_RELEASE_REASON
    assert int(row["objective_complete_at"] or 0) == 0
    assert int(row["invalidated_at"] or 0) == 0
    assert row["status"] in policy.ACTIVE_THESIS_STATUSES


def test_terminal_campaign_does_not_release_while_any_sequence_position_is_open(tmp_path, monkeypatch):
    snap, _, _, key, campaign = _seed_owner(tmp_path, monkeypatch)
    _heartbeat(snap.sent_at, campaign, open_positions=1, terminal=True)

    owner = policy.active_owner_snapshot(snap.sent_at)
    assert owner is not None
    assert owner["reaction_key"] == key


def test_flat_owner_does_not_release_before_reentry_cap_is_exhausted(tmp_path, monkeypatch):
    snap, _, _, key, campaign = _seed_owner(tmp_path, monkeypatch)
    _heartbeat(snap.sent_at, campaign, open_positions=0, terminal=False)

    owner = policy.active_owner_snapshot(snap.sent_at)
    assert owner is not None
    assert owner["reaction_key"] == key


def test_wrong_campaign_heartbeat_cannot_release_owner(tmp_path, monkeypatch):
    snap, _, _, key, _ = _seed_owner(tmp_path, monkeypatch)
    _heartbeat(snap.sent_at, "BUY|H4>H1|999|999", open_positions=0, terminal=True)

    owner = policy.active_owner_snapshot(snap.sent_at)
    assert owner is not None
    assert owner["reaction_key"] == key


def test_released_terminal_campaign_cannot_reacquire_same_reaction_as_new_p0(tmp_path, monkeypatch):
    snap, zone, analysis, key, campaign = _seed_owner(tmp_path, monkeypatch)
    _heartbeat(snap.sent_at, campaign, open_positions=0, terminal=True)
    assert policy.active_owner_snapshot(snap.sent_at) is None

    later = _snapshot(ts=snap.sent_at + 10)
    reacquired = policy.acquire_execution_ownership(
        analysis, later, "HTF_CORE_HANDOFF", zone.zone_id, anchor_price=100.0
    )
    assert reacquired is None

    with db.connect() as conn:
        row = conn.execute(
            "SELECT ownership_execution_released_at,objective_complete_at FROM zone_reactions WHERE reaction_key=?",
            (key,),
        ).fetchone()
    assert int(row["ownership_execution_released_at"] or 0) > 0
    assert int(row["objective_complete_at"] or 0) == 0
