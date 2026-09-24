from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .models import Direction, Grade, Zone

RISK_MODEL = "MASTER_SNIPER_CONTEXT_GRADE_MATRIX_10000_V5_BPLUS_EXEC"
RISK_CONTEXT_TREND = "TREND"
RISK_CONTEXT_COUNTERTREND = "COUNTERTREND"

# Master Sniper permanent execution contract:
# - A+, A and B+ may acquire NEW execution authority after all normal gates pass.
# - B+ is deliberately reduced-risk execution authority at 0.25%.
# - B+ remains first-qualified-mitigation only so lower structural quality is not
#   confused with A/A+ freshness.
# - Freshness is measured by qualified directional mitigation cycles only.
EXECUTION_GRADES = {Grade.A_PLUS, Grade.A, Grade.B_PLUS}


def zone_risk_context(zone: Zone) -> str:
    return RISK_CONTEXT_COUNTERTREND if bool(zone.countertrend) or str(zone.setup_type).upper() == "REVERSAL" else RISK_CONTEXT_TREND


def opposite_risk_context(context: str) -> str:
    return RISK_CONTEXT_TREND if str(context).upper() == RISK_CONTEXT_COUNTERTREND else RISK_CONTEXT_COUNTERTREND


def risk_pct_for_grade(grade: Grade, context: str) -> float:
    context = str(context).upper()
    if grade == Grade.A_PLUS:
        return float(
            SETTINGS.research_risk_pct_countertrend_a_plus
            if context == RISK_CONTEXT_COUNTERTREND
            else SETTINGS.research_risk_pct_trend_a_plus
        )
    if grade == Grade.A:
        return float(
            SETTINGS.research_risk_pct_countertrend_a
            if context == RISK_CONTEXT_COUNTERTREND
            else SETTINGS.research_risk_pct_trend_a
        )
    if grade == Grade.B_PLUS:
        return float(SETTINGS.research_risk_pct_b_plus)
    return 0.0


def original_risk_pct(zone: Zone) -> float:
    return risk_pct_for_grade(zone.grade, zone_risk_context(zone))


def flip_risk_pct(zone: Zone) -> float:
    return risk_pct_for_grade(zone.grade, opposite_risk_context(zone_risk_context(zone)))


def execution_touch_limit(zone: Zone) -> int:
    # A+ is executable through 0-1 qualified mitigations. A may remain executable
    # through the second. B+ has reduced-risk authority only while still first-touch
    # fresh; every contact must satisfy the directional qualified-mitigation audit.
    if zone.grade == Grade.A_PLUS:
        return 1
    if zone.grade == Grade.A:
        return 2
    if zone.grade == Grade.B_PLUS:
        return 1
    return -1


def execution_grade_eligible(zone: Zone) -> bool:
    return zone.grade in EXECUTION_GRADES and execution_touch_limit(zone) >= int(zone.touch_count)


def matrix_payload() -> dict[str, Any]:
    bplus = float(SETTINGS.research_risk_pct_b_plus)
    return {
        "model": RISK_MODEL,
        "validation_initial_capital": float(SETTINGS.research_validation_initial_capital),
        "compounding": False,
        "risk_base_rule": "MIN_VALIDATION_CAPITAL_OR_LIVE_BALANCE",
        "trend": {
            "A+": float(SETTINGS.research_risk_pct_trend_a_plus),
            "A": float(SETTINGS.research_risk_pct_trend_a),
            "B+": bplus,
        },
        "countertrend": {
            "A+": float(SETTINGS.research_risk_pct_countertrend_a_plus),
            "A": float(SETTINGS.research_risk_pct_countertrend_a),
            "B+": bplus,
        },
        "B+": bplus,
        "bplus_execution_authority": True,
        "touch_limits": {"A+": 1, "A": 2, "B+": 1},
        "freshness_basis": "QUALIFIED_DIRECTIONAL_MITIGATION_CYCLES_ONLY",
        "grading_contract": {
            "TREND": "continuation-source strength + qualified-mitigation freshness",
            "COUNTERTREND": "HTF extremity + structural liquidity sweep/rejection + reversal-response quality + qualified-mitigation freshness",
        },
        "note": "Master Sniper base thesis risk is context x grade before entry-share/model multipliers. B+ has executable authority at the dedicated 0.25% reduced-risk budget and still requires every normal M15/M1/AI/safety gate.",
    }


def classify_direction_context(direction: Direction, daily_context: Direction) -> str:
    if daily_context == Direction.NEUTRAL:
        return RISK_CONTEXT_TREND
    return RISK_CONTEXT_TREND if direction == daily_context else RISK_CONTEXT_COUNTERTREND
