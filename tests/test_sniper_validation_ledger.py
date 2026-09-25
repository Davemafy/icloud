from types import SimpleNamespace

from app import db
from app.models import Analysis, Direction, Grade, Zone, ZoneState
from app import sniper_validation_ledger as ledger


def _zone() -> Zone:
    return Zone(
        zone_id="PZ_H4H1_SELL_14",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=4363.94,
        core_high=4369.35,
        core_method="MASTER_SNIPER_SOURCE_EXACT",
        location_score=8.56,
        zone_low=4361.406,
        zone_high=4370.73,
        touch_count=1,
        mitigation_audit={
            "raw_contacts": [
                {
                    "raw_contact_index": 1,
                    "armed_at": 110,
                    "approach_side": "BELOW",
                    "campaign_approach_side": "BELOW",
                    "core_touched_at": 120,
                    "contact_role": "NEW_CORE_CONTACT_EPISODE",
                }
            ],
            "events": [
                {
                    "event_type": "MITIGATION",
                    "qualified": True,
                    "qualified_index": 1,
                    "armed_at": 110,
                    "approach_side": "BELOW",
                    "core_touched_at": 120,
                    "qualified_at": 130,
                    "exit_side": "BELOW",
                    "reason": "CONFIRMED_DIRECTIONAL_CORE_REACTION_COMPLETE",
                    "grade_before": "A+",
                    "grade_after": "A+",
                }
            ],
        },
        confluences=["BSL_IN_MARKED_ZONE", "H4_H1_OVERLAP"],
        independent_confluence_count=2,
        source_ts=90,
        invalidation_level=4370.73,
        invalidation_rule="M15_ACCEPTED_INVALIDATION",
        original_target1=4342.71,
        original_target2=4339.14,
        original_target3=4337.46,
        original_runner=4334.32,
        flip_target1=4371.32,
        flip_target2=4374.88,
        flip_target3=4376.17,
        flip_runner=4379.0,
        clear_run=21.23,
        countertrend=False,
        notes=[
            "structural_grade:A+",
            "current_execution_grade:A+",
            "qualified_mitigations:1",
            "raw_core_touch_episodes:1",
            "grade_degrade_reason:NONE",
        ],
    )


def _analysis(zone: Zone) -> Analysis:
    return Analysis(
        analysis_id="A_TEST",
        generated_at=100,
        snapshot_at=100,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )


def _setup(tmp_path, monkeypatch):
    settings = SimpleNamespace(db_path=str(tmp_path / "ledger.db"), ml_data_enabled=False)
    monkeypatch.setattr(db, "SETTINGS", settings)
    db.init_db()
    ledger.ensure_execution_ownership_schema()
    ledger.ensure_zone_publication_schema()


def test_empty_validation_ledger_is_read_only(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    out = ledger.build_validation_ledger()
    assert out["contract"] == ledger.VALIDATION_LEDGER_VERSION
    assert out["read_only"] is True
    assert out["summary"]["publications"] == 0
    assert out["rows"] == []


def test_validation_ledger_combines_publication_mitigation_handoff_and_trade_truth(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    zone = _zone()
    analysis = _analysis(zone)

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO analyses(ts,analysis_id,payload,ai_ok) VALUES(?,?,?,?)",
            (100, analysis.analysis_id, analysis.model_dump_json(), 1),
        )
        conn.execute(
            """
            INSERT INTO zone_publications(
                publication_key,reaction_key,geometry_signature,first_analysis_id,latest_analysis_id,
                zone_id,direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,
                first_published_at,last_seen_at,publication_qualified_mitigations,
                publication_raw_core_contacts,live_core_touched_at,live_core_touch_basis,
                live_core_touch_price,live_core_touch_analysis_id,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "PUB1","RX1","SIG1","A_TEST","A_TEST",zone.zone_id,"SELL","H4>H1",90,
                zone.core_low,zone.core_high,zone.zone_low,zone.zone_high,
                100,180,0,0,120,"LIVE_QUOTE_OVERLAP",4365.0,"A_TEST","LIVE_CONTACT_CONFIRMED",
            ),
        )
        conn.execute(
            """
            INSERT INTO zone_reactions(
                reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
                target1,target2,target3,runner,target1_hit_at,target2_hit_at,target3_hit_at,
                objective_complete_at,invalidated_at,best_price,mfe_price,last_reason,
                ownership_acquired_at,ownership_authority,ownership_analysis_id,ownership_anchor_price,
                ownership_zone_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "RX1","A_TEST","A_TEST",zone.zone_id,zone.zone_id,"SELL","H4>H1",90,
                zone.core_low,zone.core_high,zone.zone_low,zone.zone_high,"A+","OBJECTIVE_IN_PROGRESS",
                100,180,120,140,
                zone.original_target1,zone.original_target2,zone.original_target3,zone.original_runner,
                170,0,0,0,0,4339.5,30.0,"LIQUIDITY_OBJECTIVE_PROGRESS",
                145,"HTF_CORE_HANDOFF","A_TEST",4365.0,zone.zone_id,
            ),
        )
        conn.execute(
            "INSERT INTO feedback(ts,event,analysis_id,zone_id,price,details) VALUES(?,?,?,?,?,?)",
            (150,"ENTRY_OPENED","A_TEST",zone.zone_id,4364.5,'{"position_id":77,"deal_id":88,"setup":"CONTINUATION","grade":"A+","sequence_version":"3.42"}'),
        )
        conn.execute(
            "INSERT INTO feedback(ts,event,analysis_id,zone_id,price,details) VALUES(?,?,?,?,?,?)",
            (175,"TRADE_CLOSED","A_TEST",zone.zone_id,4342.5,'{"position_id":77,"setup":"CONTINUATION","grade":"A+","sequence_version":"3.42"}'),
        )

    out = ledger.build_validation_ledger()
    assert out["summary"]["publications"] == 1
    assert out["summary"]["live_contacts"] == 1
    assert out["summary"]["reaction_confirmed"] == 1
    assert out["summary"]["executed_publications"] == 1

    row = out["rows"][0]
    assert row["zone_id"] == zone.zone_id
    assert row["structural_grade"] == "A+"
    assert row["current_grade"] == "A+"
    assert row["qualified_mitigations"] == 1
    assert row["handoff_authority"] == "HTF_CORE_HANDOFF"
    assert row["execution_state"] == "CLOSED"
    assert row["outcome"] == "OBJECTIVE_PROGRESS"
    names = [event["event"] for event in row["events"]]
    assert "ZONE_PUBLISHED" in names
    assert "APPROACH_ARMED" in names
    assert "LIVE_CORE_CONTACT" in names
    assert "QUALIFIED_MITIGATION" in names
    assert "REACTION_CONFIRMED" in names
    assert "M1_HANDOFF_ACQUIRED" in names
    assert "ENTRY_OPENED" in names
    assert "TARGET_1_HIT" in names
    assert "TRADE_CLOSED" in names


def test_validation_ledger_marks_invalidation_before_reaction_without_calling_it_a_bad_zone(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    zone = _zone()
    zone.mitigation_audit = {}
    zone.notes = ["structural_grade:A+", "current_execution_grade:A+"]
    analysis = _analysis(zone)

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO analyses(ts,analysis_id,payload,ai_ok) VALUES(?,?,?,?)",
            (100, analysis.analysis_id, analysis.model_dump_json(), 1),
        )
        conn.execute(
            """
            INSERT INTO zone_publications(
                publication_key,reaction_key,geometry_signature,first_analysis_id,latest_analysis_id,
                zone_id,direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,
                first_published_at,last_seen_at,publication_qualified_mitigations,
                publication_raw_core_contacts,live_core_touched_at,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "PUB2","RX2","SIG2","A_TEST","A_TEST",zone.zone_id,"SELL","H4>H1",90,
                zone.core_low,zone.core_high,zone.zone_low,zone.zone_high,100,160,0,0,120,"LIVE_CONTACT_CONFIRMED",
            ),
        )
        conn.execute(
            """
            INSERT INTO zone_reactions(
                reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
                target1,target2,target3,runner,invalidated_at,best_price,mfe_price,last_reason
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "RX2","A_TEST","A_TEST",zone.zone_id,zone.zone_id,"SELL","H4>H1",90,
                zone.core_low,zone.core_high,zone.zone_low,zone.zone_high,"A+","INVALIDATED",
                100,160,120,0,zone.original_target1,zone.original_target2,zone.original_target3,zone.original_runner,
                160,4372.0,0.0,"M15_ACCEPTED_INVALIDATION",
            ),
        )

    out = ledger.build_validation_ledger()
    row = out["rows"][0]
    assert row["outcome"] == "INVALIDATED_BEFORE_REACTION"
    assert row["execution_state"] == "NO_ENTRY"
    assert any(event["event"] == "ACCEPTED_INVALIDATION" for event in row["events"])
    assert "bad_zone" not in row
