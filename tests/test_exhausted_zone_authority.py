from app.models import Direction, Grade, Zone, ZoneState
from app.risk_matrix import execution_authority_status, execution_grade_eligible, matrix_payload


def _zone(grade: Grade, touches: int, notes=None) -> Zone:
    return Zone(
        zone_id="PZ_TEST",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H1",
        grade=grade,
        state=ZoneState.ACTIVE,
        core_low=100.0,
        core_high=101.0,
        core_method="WATCH|MASTER_SNIPER_SOURCE_EXACT",
        location_score=8.0,
        zone_low=100.0,
        zone_high=103.0,
        touch_count=touches,
        source_ts=1,
        invalidation_level=103.0,
        invalidation_rule="accepted M15 invalidation",
        notes=list(notes or []),
    )


def test_high_touch_count_is_telemetry_only_for_active_zone():
    zone = _zone(Grade.A_PLUS, 40, ["grade_degrade_reason:EXHAUSTED_3PLUS_QUALIFIED_MITIGATIONS"])
    assert zone.state == ZoneState.ACTIVE
    assert execution_authority_status(zone) == "EXECUTION_ELIGIBLE"
    assert execution_grade_eligible(zone) is True


def test_legacy_exhaustion_note_cannot_override_current_immutable_grade_contract():
    zone = _zone(Grade.B_PLUS, 0, ["grade_degrade_reason:EXHAUSTED_3PLUS_QUALIFIED_MITIGATIONS"])
    assert execution_authority_status(zone) == "EXECUTION_ELIGIBLE"
    assert execution_grade_eligible(zone) is True


def test_structural_bplus_retains_reduced_risk_execution_eligibility():
    zone = _zone(Grade.B_PLUS, 20, ["grade_degrade_reason:STRUCTURAL_QUALITY_BELOW_A"])
    assert execution_authority_status(zone) == "EXECUTION_ELIGIBLE"
    assert execution_grade_eligible(zone) is True


def test_matrix_exports_touch_telemetry_only_contract():
    payload = matrix_payload()
    assert payload["touch_authority"]["state"] == "TELEMETRY_ONLY"
    assert payload["touch_authority"]["changes_grade"] is False
    assert payload["touch_authority"]["changes_risk"] is False
    assert payload["touch_authority"]["changes_ranking"] is False
    assert payload["touch_authority"]["changes_execution_eligibility"] is False
    assert payload["exhaustion_authority"]["state"] == "DISABLED_TOUCH_COUNT_NEVER_BLOCKS"
