from app import db
from app.db import save_snapshot
from app.execution_owner_mirror import (
    OWNER_MIRROR_CONTRACT,
    owner_plan_text,
    recover_owner_from_sequence_heartbeat,
)
from app.execution_ownership_migration import ensure_execution_ownership_schema
from app.models import Bar, Heartbeat, MarketSnapshot
from app.thesis_ownership_policy import active_owner_snapshot


def _snapshot(ts=2000, mid=100.0):
    return MarketSnapshot(
        sent_at=ts,
        bid=mid - 0.08,
        ask=mid + 0.08,
        spread_points=16,
        point=0.01,
        atr_h1=8.0,
        atr_m15=2.0,
        xau_m15=[
            Bar(ts=ts-900, open=100.0, high=101.0, low=99.0, close=100.2),
            Bar(ts=ts-60, open=100.2, high=100.8, low=99.5, close=100.0),
        ],
    )


def _insert_owner():
    ensure_execution_ownership_schema()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO zone_reactions(
                reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
                target1,target2,target3,runner,target1_hit_at,target2_hit_at,target3_hit_at,
                objective_complete_at,invalidated_at,best_price,mfe_price,last_reason,
                ownership_acquired_at,ownership_authority,ownership_analysis_id,ownership_anchor_price,
                ownership_zone_id,ownership_zone_payload
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "SELL|H4>H1|777","A1","A1","Z1","Z1","SELL","H4>H1",777,
                104.0,105.0,95.0,106.0,"A+","OBJECTIVE_IN_PROGRESS",
                1000,1900,1100,1150,90.0,85.0,80.0,0.0,1200,0,0,0,0,88.0,16.0,
                "LIQUIDITY_OBJECTIVE_PROGRESS",1120,"HTF_CORE_HANDOFF","A1",104.5,"Z1",""
            ),
        )


def test_plan_exports_active_owner_for_mt5_local_mirror(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_path", lambda: str(tmp_path / "mirror_plan.db"))
    db.init_db()
    _insert_owner()
    text = owner_plan_text(2000)
    assert "owner_mirror_contract=MT5_EXECUTION_OWNER_MIRROR_V1" in text
    assert "owner_mirror_active=1" in text
    assert "owner_mirror_zone_id=Z1" in text
    assert "owner_mirror_status=OBJECTIVE_IN_PROGRESS" in text
    assert "owner_mirror_target1_hit_at=1200" in text
    assert "owner_mirror_target2=85.0" in text


def test_sequence_heartbeat_restores_owner_after_cloud_database_loss(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_path", lambda: str(tmp_path / "mirror_restore.db"))
    db.init_db()
    save_snapshot(_snapshot())

    details = {
        "paper_only": True,
        "owner_mirror_contract": OWNER_MIRROR_CONTRACT,
        "owner_mirror_active": True,
        "owner_mirror_saved_at": 1900,
        "owner_mirror_analysis_id": "A_OLD_OWNER",
        "owner_mirror_zone_id": "PZ_OWNER",
        "owner_mirror_direction": "SELL",
        "owner_mirror_source_tf": "H4>H1",
        "owner_mirror_source_ts": 777,
        "owner_mirror_grade": "A+",
        "owner_mirror_status": "OBJECTIVE_IN_PROGRESS",
        "owner_mirror_authority": "HTF_CORE_HANDOFF",
        "owner_mirror_acquired_at": 1500,
        "owner_mirror_core_low": 104.0,
        "owner_mirror_core_high": 105.0,
        "owner_mirror_zone_low": 95.0,
        "owner_mirror_zone_high": 106.0,
        "owner_mirror_target1": 90.0,
        "owner_mirror_target2": 85.0,
        "owner_mirror_target3": 80.0,
        "owner_mirror_target1_hit_at": 1700,
        "owner_mirror_target2_hit_at": 0,
        "owner_mirror_target3_hit_at": 0,
        "owner_mirror_reaction_confirmed_at": 1600,
        "owner_mirror_best_price": 88.0,
    }
    h = Heartbeat(ts=2000, ea="InstitutionalSMC_SequenceEA", version="3.30", symbol="XAUUSD", details=details)
    assert active_owner_snapshot(2000) is None
    assert recover_owner_from_sequence_heartbeat(h) is True

    owner = active_owner_snapshot(2000)
    assert owner is not None
    assert owner["ownership_zone_id"] == "PZ_OWNER"
    assert owner["status"] == "OBJECTIVE_IN_PROGRESS"
    assert int(owner["target1_hit_at"]) == 1700
    assert float(owner["target2"]) == 85.0
    assert owner["last_reason"] == "RESTORED_FROM_MT5_OWNER_MIRROR"


def test_mirror_recovery_refuses_completed_deepest_objective(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_path", lambda: str(tmp_path / "mirror_terminal.db"))
    db.init_db()
    save_snapshot(_snapshot(mid=79.0))
    h = Heartbeat(
        ts=2000, ea="InstitutionalSMC_SequenceEA", version="3.30", symbol="XAUUSD",
        details={
            "paper_only": True,
            "owner_mirror_contract": OWNER_MIRROR_CONTRACT,
            "owner_mirror_active": True,
            "owner_mirror_saved_at": 1900,
            "owner_mirror_analysis_id": "A1",
            "owner_mirror_zone_id": "Z1",
            "owner_mirror_direction": "SELL",
            "owner_mirror_source_tf": "H4>H1",
            "owner_mirror_source_ts": 777,
            "owner_mirror_grade": "A+",
            "owner_mirror_status": "OBJECTIVE_IN_PROGRESS",
            "owner_mirror_authority": "HTF_CORE_HANDOFF",
            "owner_mirror_acquired_at": 1500,
            "owner_mirror_core_low": 104.0,
            "owner_mirror_core_high": 105.0,
            "owner_mirror_zone_low": 95.0,
            "owner_mirror_zone_high": 106.0,
            "owner_mirror_target1": 90.0,
            "owner_mirror_target2": 85.0,
            "owner_mirror_target3": 80.0,
            "owner_mirror_best_price": 79.0,
        },
    )
    assert recover_owner_from_sequence_heartbeat(h) is False
    assert active_owner_snapshot(2000) is None
