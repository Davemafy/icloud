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


def _watch(core_low=99.5, core_high=100.5, source_tf="H1", grade=Grade.A) -> Zone:
    return Zone(
        zone_id="Z1",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="REVERSAL",
        source_tf=source_tf,
        grade=grade,
        state=ZoneState.ACTIVE,
        core_low=core_low,
        core_high=core_high,
        core_method="WATCH|H1_INDEPENDENT_TACTICAL|M15_REFINED",
        location_score=8.0,
        zone_low=95.0,
        zone_high=101.0,
        touch_count=1,
        independent_confluence_count=3,
        clear_run=8.0,
    )


def test_watch_interaction_uses_core_not_broad_envelope():
    s = _snapshot(100.0)
    z = _watch()
    assert watch_zone_ready(z, s) is True


def test_distant_core_does_not_become_ready_even_if_envelope_is_wide():
    s = _snapshot(100.0)
    z = _watch(core_low=90.0, core_high=91.0)
    z.zone_low = 89.0
    z.zone_high = 101.0
    assert watch_zone_ready(z, s) is False


def test_context_or_h4_parent_is_not_promoted():
    s = _snapshot(100.0)
    z = _watch(source_tf="H4")
    assert watch_zone_ready(z, s) is False


def test_promote_sets_selected_zone_and_m1_ready_marker():
    s = _snapshot(100.0)
    z = _watch()
    a = Analysis(analysis_id="A1", generated_at=1, snapshot_at=1, zones=[z])
    selected = promote_watch_to_m1_ready(a, s)
    assert selected is z
    assert a.selected_zone_id == "Z1"
    assert z.core_method.startswith("M1_READY|")
    assert "readiness:M1_READY" in z.notes
