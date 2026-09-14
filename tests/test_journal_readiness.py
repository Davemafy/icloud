from app import service
from app.main import _event_status, _selected_zone
from app.models import Analysis, Direction, Grade, Zone, ZoneState


def _zone():
    return Zone(
        zone_id="Z1",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="REVERSAL",
        source_tf="H1",
        grade=Grade.A,
        state=ZoneState.ACTIVE,
        core_low=100.0,
        core_high=101.0,
        core_method="WATCH|H1_INDEPENDENT_TACTICAL|M15_REFINED",
        location_score=8.0,
        zone_low=99.5,
        zone_high=101.5,
        invalidation_level=99.5,
        invalidation_rule="test",
    )


def test_watch_zone_is_not_promoted_when_no_actionable_selection():
    z = _zone()
    a = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        zones=[z],
        selected_zone_id="",
    )
    assert _selected_zone(a) is None
    assert _event_status([], "") == "WAITING"


def test_selected_actionable_zone_is_returned_explicitly():
    z = _zone()
    z.core_method = "ACTIONABLE|H1_INDEPENDENT_TACTICAL|M15_REFINED"
    a = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        zones=[z],
        selected_zone_id="Z1",
    )
    assert _selected_zone(a).zone_id == "Z1"


def test_active_analysis_uses_newest_analysis_not_stale_ai_approved(monkeypatch):
    calls = []

    def fake_latest_analysis(ai_required=False):
        calls.append(ai_required)
        return "LATEST"

    monkeypatch.setattr(service, "latest_analysis", fake_latest_analysis)
    assert service.active_analysis() == "LATEST"
    assert calls == [False]
