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


def test_only_a_plus_and_a_can_acquire_new_execution_authority():
    assert EXECUTION_GRADES == {Grade.A_PLUS, Grade.A}
    assert execution_grade_eligible(_zone(Grade.A_PLUS, 0))
    assert execution_grade_eligible(_zone(Grade.A_PLUS, 1))
    assert not execution_grade_eligible(_zone(Grade.A_PLUS, 2))
    assert execution_grade_eligible(_zone(Grade.A, 2))
    assert not execution_grade_eligible(_zone(Grade.A, 3))
    assert not execution_grade_eligible(_zone(Grade.B_PLUS, 0))


def test_bplus_is_watch_only_with_zero_new_entry_risk():
    assert execution_touch_limit(_zone(Grade.B_PLUS, 0)) == -1
    assert risk_pct_for_grade(Grade.B_PLUS, "TREND") == 0.0
    assert risk_pct_for_grade(Grade.B_PLUS, "COUNTERTREND") == 0.0
    payload = matrix_payload()
    assert payload["bplus_execution_authority"] is False
    assert payload["B+"] == 0.0
    assert payload["trend"]["B+"] == 0.0
    assert payload["countertrend"]["B+"] == 0.0


def test_master_sniper_context_grade_risk_budgets_remain_proportional():
    assert risk_pct_for_grade(Grade.A_PLUS, "TREND") == 1.00
    assert risk_pct_for_grade(Grade.A, "TREND") == 0.75
    assert risk_pct_for_grade(Grade.A_PLUS, "COUNTERTREND") == 0.50
    assert risk_pct_for_grade(Grade.A, "COUNTERTREND") == 0.25
