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


def test_repeated_same_source_core_is_one_canonical_sample_and_rate_cannot_exceed_100(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    zone = _zone()

    with db.connect() as conn:
        # Same institutional source/core, but two exact envelope publications from
        # later reanalysis. The raw audit records stay distinct in SQL.
        for values in (
            (
                "PUB_D1","RX_D","SIG_D1","A_D1","A_D1",zone.zone_id,"SELL","H4>H1",90,
                zone.core_low,zone.core_high,4361.40,4370.70,
                100,130,0,0,0,"",0.0,"","PUBLISHED",
            ),
            (
                "PUB_D2","RX_D","SIG_D2","A_D2","A_D2",zone.zone_id,"SELL","H4>H1",90,
                zone.core_low,zone.core_high,4361.35,4370.75,
                140,200,0,0,150,"LIVE_QUOTE_OVERLAP",4365.0,"A_D2","LIVE_CONTACT_CONFIRMED",
            ),
        ):
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
                values,
            )

        conn.execute(
            """
            INSERT INTO zone_reactions(
                reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
                target1,target2,target3,runner,best_price,mfe_price,last_reason
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "RX_D","A_D1","A_D2",zone.zone_id,zone.zone_id,"SELL","H4>H1",90,
                zone.core_low,zone.core_high,4361.35,4370.75,"A+","REACTION_CONFIRMED",
                100,200,150,160,
                zone.original_target1,zone.original_target2,zone.original_target3,zone.original_runner,
                4350.0,15.0,"REACTION_CONFIRMED",
            ),
        )

    out = ledger.build_validation_ledger(limit=50)

    assert out["summary"]["publications"] == 1
    assert out["summary"]["raw_publication_records"] == 2
    assert out["summary"]["live_contacts"] == 1
    assert out["summary"]["reaction_confirmed"] == 1
    assert out["summary"]["reaction_confirmed_after_live_contact"] == 1
    assert out["summary"]["reaction_rate_after_contact_pct"] == 100.0
    assert out["summary"]["reaction_rate_after_contact_pct"] <= 100.0
    assert len(out["rows"]) == 1
    assert out["rows"][0]["publication_observation_count"] == 2
    assert out["rows"][0]["published_at"] == 100
    assert out["rows"][0]["live_core_touched_at"] == 150


def test_reaction_without_live_core_contact_does_not_inflate_after_contact_rate(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    zone = _zone()

    with db.connect() as conn:
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
                "PUB_NC","RX_NC","SIG_NC","A_NC","A_NC",zone.zone_id,"SELL","H4>H1",90,
                zone.core_low,zone.core_high,zone.zone_low,zone.zone_high,100,180,0,0,0,"PUBLISHED",
            ),
        )
        conn.execute(
            """
            INSERT INTO zone_reactions(
                reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
                target1,target2,target3,runner,best_price,mfe_price,last_reason
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "RX_NC","A_NC","A_NC",zone.zone_id,zone.zone_id,"SELL","H4>H1",90,
                zone.core_low,zone.core_high,zone.zone_low,zone.zone_high,"A+","REACTION_CONFIRMED",
                100,180,0,140,
                zone.original_target1,zone.original_target2,zone.original_target3,zone.original_runner,
                4350.0,15.0,"HTF_ZONE_SWEEP_HANDOFF",
            ),
        )

    out = ledger.build_validation_ledger()

    assert out["summary"]["live_contacts"] == 0
    assert out["summary"]["reaction_confirmed"] == 1
    assert out["summary"]["reaction_confirmed_after_live_contact"] == 0
    assert out["summary"]["reaction_confirmed_without_live_core_contact"] == 1
    assert out["summary"]["reaction_rate_after_contact_pct"] is None


def test_trade_event_with_zone_id_never_leaks_to_sibling_zone_in_same_analysis(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sell = _zone()
    buy = sell.model_copy(deep=True)
    buy.zone_id = "PZ_H4H1_BUY_15"
    buy.original_direction = Direction.BUY
    buy.flip_direction = Direction.SELL
    buy.source_ts = 91
    buy.core_low = 4145.27
    buy.core_high = 4156.15
    buy.zone_low = 4139.13
    buy.zone_high = 4156.15

    analysis = Analysis(
        analysis_id="A_SHARED",
        generated_at=100,
        snapshot_at=100,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id=buy.zone_id,
        approved=True,
        ai_approved=True,
    )

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO analyses(ts,analysis_id,payload,ai_ok) VALUES(?,?,?,?)",
            (100, analysis.analysis_id, analysis.model_dump_json(), 1),
        )
        for pub, rx, zone in (("PUB_SELL","RX_SELL",sell),("PUB_BUY","RX_BUY",buy)):
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
                    pub,rx,pub + "_SIG","A_SHARED","A_SHARED",zone.zone_id,zone.original_direction.value,
                    "H4>H1",zone.source_ts,zone.core_low,zone.core_high,zone.zone_low,zone.zone_high,
                    100,200,0,0,0,"PUBLISHED",
                ),
            )

        conn.execute(
            "INSERT INTO feedback(ts,event,analysis_id,zone_id,price,details) VALUES(?,?,?,?,?,?)",
            (150,"ENTRY_OPENED","A_SHARED",buy.zone_id,4153.43,'{"position_id":9001,"setup":"PRIMARY","grade":"B+"}'),
        )
        conn.execute(
            "INSERT INTO feedback(ts,event,analysis_id,zone_id,price,details) VALUES(?,?,?,?,?,?)",
            (170,"TRADE_CLOSED","A_SHARED",buy.zone_id,4160.46,'{"position_id":9001,"setup":"PRIMARY","grade":"B+"}'),
        )

    out = ledger.build_validation_ledger(limit=10)
    rows = {row["zone_id"]: row for row in out["rows"]}
    assert rows[buy.zone_id]["execution_state"] == "CLOSED"
    assert rows[sell.zone_id]["execution_state"] == "NO_ENTRY"
    assert out["summary"]["executed_publications"] == 1


def test_canonical_ledger_keeps_first_publication_after_more_than_old_raw_window(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    zone = _zone()
    analysis = _analysis(zone)

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO analyses(ts,analysis_id,payload,ai_ok) VALUES(?,?,?,?)",
            (100, analysis.analysis_id, analysis.model_dump_json(), 1),
        )
        # More observations than the old limit*12 raw-row window. Geometry
        # envelope drifts, but source/core identity is intentionally unchanged.
        for i in range(650):
            ts = 100 + i
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
                    f"PUB_MANY_{i}","RX_MANY",f"SIG_MANY_{i}","A_TEST","A_TEST",
                    zone.zone_id,"SELL","H4>H1",90,zone.core_low,zone.core_high,
                    zone.zone_low,zone.zone_high + i * 0.00001,
                    ts,ts,0,0,
                    110 if i == 0 else 0,
                    "LIVE_QUOTE_OVERLAP" if i == 0 else "",
                    4365.0 if i == 0 else 0.0,
                    "A_TEST" if i == 0 else "",
                    "LIVE_CONTACT_CONFIRMED" if i == 0 else "PUBLISHED",
                ),
            )

        conn.execute(
            "INSERT INTO feedback(ts,event,analysis_id,zone_id,price,details) VALUES(?,?,?,?,?,?)",
            (120,"ENTRY_OPENED","A_TEST",zone.zone_id,4364.5,'{"position_id":7001,"setup":"PRIMARY","grade":"A+"}'),
        )
        conn.execute(
            "INSERT INTO feedback(ts,event,analysis_id,zone_id,price,details) VALUES(?,?,?,?,?,?)",
            (130,"TRADE_CLOSED","A_TEST",zone.zone_id,4358.0,'{"position_id":7001,"setup":"PRIMARY","grade":"A+"}'),
        )

    out = ledger.build_validation_ledger(limit=50)
    assert out["summary"]["publications"] == 1
    assert out["summary"]["raw_publication_records"] == 650
    row = out["rows"][0]
    assert row["published_at"] == 100
    assert row["live_core_touched_at"] == 110
    assert row["publication_observation_count"] == 650
    assert row["execution_state"] == "CLOSED"
    assert out["summary"]["executed_publications"] == 1
