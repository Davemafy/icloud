import pytest
from app import db
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.watch_ready import promote_watch_to_m1_ready, watch_zone_ready
from app.zone_reaction_lifecycle import register_analysis_zones


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "watch_ready.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()


def _publish(zones, ts: int = 1, analysis_id: str = "A_PUB", bias: Direction = Direction.NEUTRAL):
    a = Analysis(
        analysis_id=analysis_id,
        generated_at=ts,
        snapshot_at=ts,
        overall_bias=bias,
        zones=list(zones),
        selected_zone_id=zones[0].zone_id if zones else "",
    )
    register_analysis_zones(a)
    return a


def _snapshot(mid: float = 100.0, ts: int = 1) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=ts,
        bid=mid - 0.1,
        ask=mid + 0.1,
        spread_points=20.0,
        point=0.01,
        atr_h1=10.0,
        atr_m15=2.0,
    )


def _zone(
    core_low=99.5,
    core_high=100.5,
    source_tf="H1",
    grade=Grade.A,
    readiness="WATCH",
    direction=Direction.BUY,
    touches=1,
    zone_id="Z1",
) -> Zone:
    required = "SSL_IN_MARKED_ZONE" if direction == Direction.BUY else "BSL_IN_MARKED_ZONE"
    return Zone(
        zone_id=zone_id,
        original_direction=direction,
        flip_direction=direction.opposite(),
        setup_type="REVERSAL",
        source_tf=source_tf,
        grade=grade,
        state=ZoneState.ACTIVE,
        core_low=core_low,
        core_high=core_high,
        core_method=f"{readiness}|PRIMARY_TEST",
        location_score=8.0,
        zone_low=95.0,
        zone_high=105.0,
        touch_count=touches,
        independent_confluence_count=4,
        confluences=["INSTITUTIONAL_DISPLACEMENT", "LIQUIDITY_IN_MARKED_ZONE", required],
        clear_run=8.0,
        source_ts=777,
        invalidation_level=105.0 if direction == Direction.SELL else 95.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=90.0 if direction == Direction.SELL else 110.0,
    )


def test_interaction_uses_core_not_broad_envelope():
    s = _snapshot(100.0)
    z = _zone()
    _publish([z], ts=s.sent_at)
    assert watch_zone_ready(z, s) is True


def test_distant_core_does_not_become_ready_even_if_envelope_is_wide():
    s = _snapshot(100.0)
    z = _zone(core_low=90.0, core_high=91.0)
    z.zone_low = 89.0
    z.zone_high = 101.0
    _publish([z], ts=s.sent_at)
    assert watch_zone_ready(z, s) is False


def test_h4_primary_parent_can_become_ready():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4", readiness="INTERACTING")
    _publish([z], ts=s.sent_at)
    assert watch_zone_ready(z, s) is True


def test_missing_required_liquidity_blocks_ready():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4", readiness="INTERACTING")
    z.confluences = ["INSTITUTIONAL_DISPLACEMENT"]
    _publish([z], ts=s.sent_at)
    assert watch_zone_ready(z, s) is False


def test_wrong_liquidity_side_blocks_ready():
    s = _snapshot(100.0)
    z = _zone(direction=Direction.SELL, readiness="INTERACTING")
    z.confluences = ["INSTITUTIONAL_DISPLACEMENT", "LIQUIDITY_IN_MARKED_ZONE", "SSL_IN_MARKED_ZONE"]
    _publish([z], ts=s.sent_at)
    assert watch_zone_ready(z, s) is False


def test_second_mitigation_a_grade_remains_ready():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4>H1", readiness="INTERACTING", touches=2)
    _publish([z], ts=s.sent_at)
    assert watch_zone_ready(z, s) is True


def test_armed_zone_stays_not_ready_until_core_interaction():
    s = _snapshot(100.0)
    z = _zone(core_low=105.0, core_high=106.0, source_tf="H4", readiness="ARMED")
    _publish([z], ts=s.sent_at)
    assert watch_zone_ready(z, s) is False


def test_promote_sets_selected_zone_and_m1_ready_marker():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4>H1", readiness="INTERACTING")
    a = Analysis(analysis_id="A1", generated_at=1, snapshot_at=1, zones=[z])
    register_analysis_zones(a)
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is z
    assert a.selected_zone_id == "Z1"
    assert z.core_method.startswith("M1_READY|")
    assert "readiness:M1_READY" in z.notes
    assert a.execution_policy["execution_window"]["mode"] == "CORE_NOW"


def test_no_owner_countertrend_interaction_can_override_remote_d1_plan_selection():
    s = _snapshot(100.0)
    sell = _zone(
        zone_id="SELL_REMOTE",
        core_low=110.0,
        core_high=111.0,
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        readiness="ARMED",
        direction=Direction.SELL,
    )
    buy = _zone(
        zone_id="BUY_LOCAL",
        core_low=99.5,
        core_high=100.5,
        source_tf="H1",
        grade=Grade.A,
        readiness="INTERACTING",
        direction=Direction.BUY,
    )
    a = Analysis(
        analysis_id="A_COUNTER",
        generated_at=1,
        snapshot_at=1,
        overall_bias=Direction.SELL,
        zones=[sell, buy],
        selected_zone_id="SELL_REMOTE",
    )
    register_analysis_zones(a)

    selected = promote_watch_to_m1_ready(a, s)

    assert selected is buy
    assert a.selected_zone_id == "BUY_LOCAL"
    assert buy.core_method.startswith("M1_READY|")
    competition = a.execution_policy["m1_authority_competition"]
    assert competition["initial_selected_zone_id"] == "SELL_REMOTE"
    assert competition["winner_zone_id"] == "BUY_LOCAL"
    assert competition["winner_direction"] == "BUY"
    assert competition["winner_overrode_plan_selection"] is True


def test_d1_context_breaks_tie_only_after_live_location_and_grade():
    s = _snapshot(100.0)
    sell = _zone(
        zone_id="SELL_LOCAL",
        core_low=99.5,
        core_high=100.5,
        source_tf="H1",
        grade=Grade.A,
        readiness="INTERACTING",
        direction=Direction.SELL,
    )
    buy = _zone(
        zone_id="BUY_LOCAL",
        core_low=99.5,
        core_high=100.5,
        source_tf="H1",
        grade=Grade.A,
        readiness="INTERACTING",
        direction=Direction.BUY,
    )
    a = Analysis(
        analysis_id="A_TIE",
        generated_at=1,
        snapshot_at=1,
        overall_bias=Direction.SELL,
        zones=[buy, sell],
        selected_zone_id="BUY_LOCAL",
    )
    register_analysis_zones(a)

    selected = promote_watch_to_m1_ready(a, s)

    assert selected is sell
    assert a.selected_zone_id == "SELL_LOCAL"


def test_preselected_armed_plan_is_visible_but_not_m1_ready_when_far():
    s = _snapshot(100.0)
    z = _zone(core_low=110.0, core_high=111.0, source_tf="H4", readiness="ARMED")
    a = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        zones=[z],
        selected_zone_id="Z1",
    )
    register_analysis_zones(a)
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is None
    assert a.selected_zone_id == "Z1"
    assert z.core_method.startswith("ARMED|")


def test_recent_qualified_core_touch_latches_m1_window_outside_core(tmp_path, monkeypatch):
    path = tmp_path / "reaction_window.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    z = _zone(source_tf="H4>H1", readiness="INTERACTING", direction=Direction.SELL)
    a = Analysis(
        analysis_id="A_WINDOW",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[z],
        selected_zone_id="Z1",
    )
    register_analysis_zones(a)
    with db.connect() as conn:
        conn.execute(
            "UPDATE zone_reactions SET core_touched_at=?,status='INTERACTING',target1=?,target1_hit_at=0 WHERE reaction_key=?",
            (1000, 90.0, "SELL|H4>H1|777"),
        )
        conn.execute(
            "UPDATE zone_publications SET live_core_touched_at=?,live_core_touch_basis='TEST_LIVE' WHERE zone_id=?",
            (1000, "Z1"),
        )

    # Price has left the 99.5-100.5 tactical core but TP1 remains meaningfully open.
    s = _snapshot(97.0, ts=1120)
    assert watch_zone_ready(z, s) is True
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is z
    assert z.core_method.startswith("M1_READY|REACTION_WINDOW|")
    window = a.execution_policy["execution_window"]
    assert window["latched"] is True
    assert window["micro_may_complete_outside_core"] is True
    assert window["core_touched_at"] == 1000


def test_reaction_window_closes_after_tp1_is_hit(tmp_path, monkeypatch):
    path = tmp_path / "reaction_window_tp1.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    z = _zone(source_tf="H4>H1", readiness="INTERACTING", direction=Direction.SELL)
    a = Analysis(
        analysis_id="A_WINDOW",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[z],
        selected_zone_id="Z1",
    )
    register_analysis_zones(a)
    with db.connect() as conn:
        conn.execute(
            "UPDATE zone_reactions SET core_touched_at=?,status='OBJECTIVE_IN_PROGRESS',target1=?,target1_hit_at=? WHERE reaction_key=?",
            (1000, 90.0, 1100, "SELL|H4>H1|777"),
        )
        conn.execute(
            "UPDATE zone_publications SET live_core_touched_at=?,live_core_touch_basis='TEST_LIVE' WHERE zone_id=?",
            (1000, "Z1"),
        )
    assert watch_zone_ready(z, _snapshot(97.0, ts=1120)) is False


def test_confirmed_a_thesis_can_continue_from_same_core_after_second_touch():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4>H1", grade=Grade.A, readiness="WATCH", touches=2)
    a = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        zones=[z],
        selected_zone_id="Z1",
        execution_policy={
            "active_thesis": {
                "locked": True,
                "owner_zone_id": "Z1",
                "direction": "BUY",
                "status": "REACTION_CONFIRMED",
                "continuation_authority": True,
            }
        },
    )
    register_analysis_zones(a)
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is z
    assert z.core_method.startswith("M1_READY|THESIS_CONTINUATION|")
    assert "execution_role:THESIS_CONTINUATION" in z.notes


def test_bplus_second_touch_zone_is_watch_only_without_primary_authority():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4>H1", grade=Grade.B_PLUS, readiness="WATCH", touches=2)
    a = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        zones=[z],
        selected_zone_id="Z1",
    )
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is None
    assert watch_zone_ready(z, s) is False


def test_bplus_third_touch_is_still_exhausted_and_blocked():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4>H1", grade=Grade.B_PLUS, readiness="WATCH", touches=3)
    assert watch_zone_ready(z, s) is False


def test_legacy_source_core_touch_without_exact_publication_touch_cannot_open_window():
    z = _zone(source_tf="H4>H1", readiness="INTERACTING", direction=Direction.SELL)
    a = _publish([z], ts=1000, analysis_id="A_LEGACY", bias=Direction.SELL)
    with db.connect() as conn:
        conn.execute(
            "UPDATE zone_reactions SET core_touched_at=?,status='INTERACTING',target1=? WHERE reaction_key=?",
            (1000, 90.0, "SELL|H4>H1|777"),
        )

    assert watch_zone_ready(z, _snapshot(97.0, ts=1120)) is False
    selected = promote_watch_to_m1_ready(a, _snapshot(97.0, ts=1120))
    assert selected is None
