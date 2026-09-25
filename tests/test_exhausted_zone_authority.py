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


def test_exhausted_bplus_is_map_only_even_while_zone_remains_active():
    zone = _zone(Grade.B_PLUS, 4, ["grade_degrade_reason:EXHAUSTED_3PLUS_QUALIFIED_MITIGATIONS"])
    assert zone.state == ZoneState.ACTIVE
    assert execution_authority_status(zone) == "MAP_ONLY_EXHAUSTED"
    assert execution_grade_eligible(zone) is False


def test_explicit_exhaustion_provenance_fails_closed_even_if_touch_count_is_stale():
    zone = _zone(Grade.B_PLUS, 0, ["grade_degrade_reason:EXHAUSTED_3PLUS_QUALIFIED_MITIGATIONS"])
    assert execution_authority_status(zone) == "MAP_ONLY_EXHAUSTED"
    assert execution_grade_eligible(zone) is False


def test_fresh_bplus_retains_reduced_risk_execution_eligibility():
    zone = _zone(Grade.B_PLUS, 1, ["grade_degrade_reason:STRUCTURAL_QUALITY_BELOW_A"])
    assert execution_authority_status(zone) == "EXECUTION_ELIGIBLE"
    assert execution_grade_eligible(zone) is True


def test_matrix_exports_permanent_exhaustion_contract():
    contract = matrix_payload()["exhaustion_authority"]
    assert contract["state"] == "MAP_ONLY_EXHAUSTED"
    assert contract["original_direction_new_execution"] is False
    assert contract["m1_reacquisition"] is False
    assert contract["context_visibility"] is True
    assert contract["flip_monitoring"] is True
    assert "ACCEPTED_M15_INVALIDATION" in contract["flip_requires"]
