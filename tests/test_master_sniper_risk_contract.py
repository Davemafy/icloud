from types import SimpleNamespace

from app.models import Direction, Grade
from app.risk_matrix import (
    EXECUTION_GRADES,
    execution_grade_eligible,
    execution_touch_limit,
    matrix_payload,
    risk_pct_for_grade,
)


def _zone(grade: Grade, touches: int):
    return SimpleNamespace(grade=grade, touch_count=touches)


def test_a_plus_a_and_bplus_authority_is_independent_of_touch_count():
    assert EXECUTION_GRADES == {Grade.A_PLUS, Grade.A, Grade.B_PLUS}
    for grade in (Grade.A_PLUS, Grade.A, Grade.B_PLUS):
        assert execution_grade_eligible(_zone(grade, 0))
        assert execution_grade_eligible(_zone(grade, 2))
        assert execution_grade_eligible(_zone(grade, 20))


def test_bplus_has_reduced_execution_authority_at_point_10_percent():
    assert execution_touch_limit(_zone(Grade.B_PLUS, 0)) > 1_000_000
    assert risk_pct_for_grade(Grade.B_PLUS, "TREND") == 0.10
    assert risk_pct_for_grade(Grade.B_PLUS, "COUNTERTREND") == 0.10
    payload = matrix_payload()
    assert payload["bplus_execution_authority"] is True
    assert payload["B+"] == 0.10
    assert payload["trend"]["B+"] == 0.10
    assert payload["countertrend"]["B+"] == 0.10


def test_master_sniper_context_grade_risk_budgets_remain_proportional():
    assert risk_pct_for_grade(Grade.A_PLUS, "TREND") == 0.300
    assert risk_pct_for_grade(Grade.A, "TREND") == 0.225
    assert risk_pct_for_grade(Grade.A_PLUS, "COUNTERTREND") == 0.150
    assert risk_pct_for_grade(Grade.A, "COUNTERTREND") == 0.075
    assert risk_pct_for_grade(Grade.B_PLUS, "TREND") == 0.10
    assert risk_pct_for_grade(Grade.B_PLUS, "COUNTERTREND") == 0.10
