from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.watch_ready import promote_watch_to_m1_ready, watch_zone_ready


def _snapshot(mid: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=1,
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
) -> Zone:
    required = "SSL_IN_MARKED_ZONE" if direction == Direction.BUY else "BSL_IN_MARKED_ZONE"
    return Zone(
        zone_id="Z1",
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
        zone_high=101.0,
        touch_count=touches,
        independent_confluence_count=4,
        confluences=["INSTITUTIONAL_DISPLACEMENT", "LIQUIDITY_IN_MARKED_ZONE", required],
        clear_run=8.0,
    )


def _confirmed_thesis_analysis(z: Zone, *, objective_open: bool = True) -> Analysis:
    return Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        zones=[z],
        selected_zone_id=z.zone_id,
        execution_policy={
            "active_thesis": {
                "locked": True,
                "owner_zone_id": z.zone_id,
                "direction": z.original_direction.value,
                "status": "REACTION_CONFIRMED",
                "continuation_authority": True,
                "objective_open": objective_open,
            }
        },
    )


def test_interaction_uses_core_not_broad_envelope():
    s = _snapshot(100.0)
    z = _zone()
    assert watch_zone_ready(z, s) is True


def test_distant_core_does_not_become_ready_even_if_envelope_is_wide():
    s = _snapshot(100.0)
    z = _zone(core_low=90.0, core_high=91.0)
    z.zone_low = 89.0
    z.zone_high = 101.0
    assert watch_zone_ready(z, s) is False


def test_h4_primary_parent_can_become_ready():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4", readiness="INTERACTING")
    assert watch_zone_ready(z, s) is True


def test_missing_required_liquidity_blocks_ready():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4", readiness="INTERACTING")
    z.confluences = ["INSTITUTIONAL_DISPLACEMENT"]
    assert watch_zone_ready(z, s) is False


def test_wrong_liquidity_side_blocks_ready():
    s = _snapshot(100.0)
    z = _zone(direction=Direction.SELL, readiness="INTERACTING")
    z.confluences = ["INSTITUTIONAL_DISPLACEMENT", "LIQUIDITY_IN_MARKED_ZONE", "SSL_IN_MARKED_ZONE"]
    assert watch_zone_ready(z, s) is False


def test_second_mitigation_blocks_ready():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4>H1", readiness="INTERACTING", touches=2)
    assert watch_zone_ready(z, s) is False


def test_armed_zone_stays_not_ready_until_core_interaction():
    s = _snapshot(100.0)
    z = _zone(core_low=105.0, core_high=106.0, source_tf="H4", readiness="ARMED")
    assert watch_zone_ready(z, s) is False


def test_promote_sets_selected_zone_and_m1_ready_marker():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4>H1", readiness="INTERACTING")
    a = Analysis(analysis_id="A1", generated_at=1, snapshot_at=1, zones=[z])
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is z
    assert a.selected_zone_id == "Z1"
    assert z.core_method.startswith("M1_READY|")
    assert "readiness:M1_READY" in z.notes


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
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is None
    assert a.selected_zone_id == "Z1"
    assert z.core_method.startswith("ARMED|")


def test_confirmed_thesis_can_continue_from_same_core_after_display_downgrade():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4>H1", grade=Grade.B_PLUS, readiness="WATCH", touches=2)
    a = _confirmed_thesis_analysis(z)
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is z
    assert z.core_method.startswith("M1_READY|THESIS_CONTINUATION|")
    assert "execution_role:THESIS_CONTINUATION" in z.notes
    assert "execution_profile:PAPER_DISCOVERY_MODE" in z.notes


def test_confirmed_thesis_discovery_mode_can_continue_away_from_original_core():
    s = _snapshot(108.0)
    z = _zone(
        core_low=99.5,
        core_high=100.5,
        source_tf="H4>H1",
        grade=Grade.B_PLUS,
        readiness="WATCH",
        touches=2,
    )
    z.zone_high = 110.0
    z.clear_run = 20.0
    a = _confirmed_thesis_analysis(z)

    # A fresh primary at this distance remains blocked, but an already-confirmed
    # paper thesis may test new M1 continuation patterns while its M15 structure
    # and liquidity objective remain alive.
    assert watch_zone_ready(z, s) is False
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is z
    assert z.core_method.startswith("M1_READY|THESIS_CONTINUATION|")


def test_confirmed_thesis_does_not_continue_after_objective_is_closed():
    s = _snapshot(108.0)
    z = _zone(
        core_low=99.5,
        core_high=100.5,
        source_tf="H4>H1",
        grade=Grade.B_PLUS,
        readiness="WATCH",
        touches=2,
    )
    z.zone_high = 110.0
    a = _confirmed_thesis_analysis(z, objective_open=False)
    assert promote_watch_to_m1_ready(a, s) is None


def test_same_bplus_second_touch_zone_has_no_new_primary_authority_without_thesis():
    s = _snapshot(100.0)
    z = _zone(source_tf="H4>H1", grade=Grade.B_PLUS, readiness="WATCH", touches=2)
    a = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        zones=[z],
        selected_zone_id="Z1",
    )
    assert promote_watch_to_m1_ready(a, s) is None