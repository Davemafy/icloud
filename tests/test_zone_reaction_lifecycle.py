from app import db
from app.models import Analysis, Bar, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.zone_reaction_lifecycle import attach_lifecycle, register_analysis_zones, update_zone_reactions


def _zone() -> Zone:
    return Zone(
        zone_id="PZ_TEST_SELL",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=100.0,
        core_high=101.0,
        core_method="PROMPT_TEST",
        location_score=9.0,
        zone_low=98.0,
        zone_high=103.0,
        touch_count=0,
        source_ts=1000,
        invalidation_level=103.0,
        invalidation_rule="M15 accepted close",
        original_target1=97.0,
        original_target2=95.0,
        original_target3=94.0,
    )


def _analysis(zones) -> Analysis:
    return Analysis(
        analysis_id="A_TEST",
        generated_at=2000,
        snapshot_at=2000,
        overall_bias=Direction.SELL,
        zones=zones,
        selected_zone_id=zones[0].zone_id if zones else "",
    )


def _snapshot(ts: int, bid: float, bars: list[Bar], atr_m15: float = 4.0) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=ts,
        bid=bid,
        ask=bid + 0.18,
        spread_points=18,
        point=0.01,
        atr_m15=atr_m15,
        xau_m15=bars,
    )


def test_confirmed_reaction_survives_later_primary_reselection(tmp_path, monkeypatch):
    path = tmp_path / "reaction.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    original = _analysis([_zone()])
    register_analysis_zones(original)

    touch = _snapshot(
        2100,
        100.5,
        [
            Bar(ts=1800, open=99.5, high=100.2, low=99.0, close=99.8),
            Bar(ts=2000, open=100.2, high=101.1, low=99.8, close=100.4),
        ],
    )
    update_zone_reactions(touch)

    reaction = _snapshot(
        2200,
        96.0,
        [
            Bar(ts=2000, open=100.2, high=101.1, low=99.8, close=100.4),
            Bar(ts=2100, open=100.0, high=100.1, low=95.8, close=96.2),
        ],
    )
    update_zone_reactions(reaction)

    later = Analysis(
        analysis_id="A_LATER",
        generated_at=2300,
        snapshot_at=2300,
        overall_bias=Direction.SELL,
        zones=[],
        selected_zone_id="",
    )
    attach_lifecycle(later)
    records = later.execution_policy["zone_reaction_lifecycle"]["records"]
    record = next(x for x in records if x["first_zone_id"] == "PZ_TEST_SELL")

    assert record["reaction_confirmed_at"] == 2200
    assert record["status"] in {"REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS", "OBJECTIVE_COMPLETE"}
    assert record["mfe_price"] >= 4.0


def test_m15_invalidation_after_reaction_preserves_success_history(tmp_path, monkeypatch):
    path = tmp_path / "reaction_after.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()
    register_analysis_zones(_analysis([_zone()]))

    update_zone_reactions(_snapshot(
        2100,100.5,[
            Bar(ts=1800, open=99.5, high=100.2, low=99.0, close=99.8),
            Bar(ts=2000, open=100.2, high=101.1, low=99.8, close=100.4),
        ],
    ))
    update_zone_reactions(_snapshot(
        2200,96.0,[
            Bar(ts=2000, open=100.2, high=101.1, low=99.8, close=100.4),
            Bar(ts=2100, open=100.0, high=100.1, low=95.8, close=96.2),
        ],
    ))

    update_zone_reactions(_snapshot(
        2300,105.0,[
            Bar(ts=2100, open=102.5, high=104.5, low=102.4, close=104.0),
            Bar(ts=2200, open=103.2, high=105.2, low=103.1, close=105.0),
        ],
    ))

    later = _analysis([])
    attach_lifecycle(later)
    record = later.execution_policy["zone_reaction_lifecycle"]["records"][0]
    assert record["status"] == "INVALIDATED_AFTER_REACTION"
    assert record["reaction_confirmed_at"] == 2200
    assert record["invalidated_at"] == 2300


def test_prezone_owner_counts_only_targets_live_beyond_ownership_anchor(tmp_path, monkeypatch):
    path = tmp_path / "reaction_anchor_truth.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()
    zone = _zone()
    register_analysis_zones(_analysis([zone]))
    key = "SELL|H4>H1|1000"

    with db.connect() as conn:
        conn.execute(
            """
            UPDATE zone_reactions
            SET status='REACTION_CONFIRMED',
                reaction_confirmed_at=2050,
                ownership_acquired_at=2050,
                ownership_authority='LIQUIDITY_REVERSAL_HANDOFF',
                ownership_analysis_id='A_PREZONE',
                ownership_anchor_price=96.0,
                ownership_zone_id=?,
                ownership_zone_payload=?,
                best_price=96.0
            WHERE reaction_key=?
            """,
            (zone.zone_id, zone.model_dump_json(), key),
        )

    progress = _snapshot(
        2200,
        94.4,
        [
            Bar(ts=2000, open=95.6, high=95.8, low=95.2, close=95.4),
            Bar(ts=2100, open=95.2, high=95.5, low=94.3, close=94.5),
        ],
        atr_m15=2.0,
    )
    update_zone_reactions(progress)

    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT status,target1_hit_at,target2_hit_at,target3_hit_at
            FROM zone_reactions WHERE reaction_key=?
            """,
            (key,),
        ).fetchone()

    # TP1=97 was already behind the SELL handoff anchor at 96, so this owner
    # cannot claim it as completed. TP2=95 was live and was crossed afterwards.
    assert int(row["target1_hit_at"] or 0) == 0
    assert int(row["target2_hit_at"] or 0) == progress.sent_at
    assert int(row["target3_hit_at"] or 0) == 0
    assert row["status"] == "OBJECTIVE_IN_PROGRESS"
