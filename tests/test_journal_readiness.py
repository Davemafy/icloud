from app import service
from app.main import _event_status, _readiness_prefix, _selected_zone, _sequence_reconciled_status
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
    assert _event_status([], "", "") == "WAITING"


def test_selected_armed_zone_reports_armed_not_planned():
    z = _zone()
    z.core_method = "ARMED|H1_INDEPENDENT_TACTICAL"
    a = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        zones=[z],
        selected_zone_id="Z1",
    )
    selected = _selected_zone(a)
    assert selected.zone_id == "Z1"
    assert _readiness_prefix(selected) == "ARMED"
    assert _event_status([], selected.state.value, "ARMED") == "ARMED"


def test_m1_ready_status_is_explicit():
    z = _zone()
    z.core_method = "M1_READY|H4H1_PRIMARY"
    assert _event_status([], z.state.value, "M1_READY") == "M1 READY"


def test_sequence_value_gate_overrides_macro_m1_ready_label():
    status = _sequence_reconciled_status(
        "M1 READY",
        {
            "online": True,
            "authority": "LIQUIDITY_REVERSAL_HANDOFF",
            "gate_stage": "VALUE_PD_ARRAY",
            "gate_reason": "WAITING_FOR_VALID_VALUE_PD_ARRAY",
            "open_positions": 0,
        },
    )
    assert status == "WAITING FOR VALUE"


def test_sequence_open_position_overrides_waiting_labels():
    status = _sequence_reconciled_status(
        "M1 READY",
        {
            "online": True,
            "authority": "LIQUIDITY_REVERSAL_HANDOFF",
            "gate_stage": "VALUE",
            "gate_reason": "SIGNAL_FOUND_WAITING_FOR_PULLBACK",
            "open_positions": 2,
        },
    )
    assert status == "IN TRADE"


def test_macro_handoff_is_not_called_ready_when_sequence_is_offline():
    assert _sequence_reconciled_status(
        "M1 READY",
        {"online": False, "authority": "NONE", "open_positions": 0},
    ) == "SEQUENCE OFFLINE"


def test_active_analysis_uses_newest_analysis_not_stale_ai_approved(monkeypatch):
    calls = []

    def fake_latest_analysis(ai_required=False):
        calls.append(ai_required)
        return "LATEST"

    monkeypatch.setattr(service, "latest_analysis", fake_latest_analysis)
    monkeypatch.setattr(service, "attach_lifecycle", lambda analysis: analysis)
    assert service.active_analysis() == "LATEST"
    assert calls == [False]
