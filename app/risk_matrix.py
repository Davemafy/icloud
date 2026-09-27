from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .models import Direction, Grade, Zone

RISK_MODEL = "MASTER_SNIPER_CONTEXT_GRADE_MATRIX_10000_V7_IMMUTABLE_ZONE_GRADE"
RISK_CONTEXT_TREND = "TREND"
RISK_CONTEXT_COUNTERTREND = "COUNTERTREND"

# Master Sniper execution contract:
# - The grade published by the institutional analysis is immutable for that
#   analysis cycle.
# - Qualified mitigation/touch history is telemetry only. It never changes grade,
#   risk, ranking, execution eligibility or M1 authority.
# - Structural invalidation or a new analysis cycle may retire/replace a zone.
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
    """Compatibility API: touch count has no execution limit in the immutable-grade model."""
    return 2_147_483_647 if zone.grade in EXECUTION_GRADES else -1


def execution_authority_status(zone: Zone) -> str:
    """Return grade authority without consulting touch/mitigation telemetry."""
    return "EXECUTION_ELIGIBLE" if zone.grade in EXECUTION_GRADES else "GRADE_BLOCKED"


def execution_grade_eligible(zone: Zone) -> bool:
    return execution_authority_status(zone) == "EXECUTION_ELIGIBLE"


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
        "touch_limits": {"A+": None, "A": None, "B+": None},
        "freshness_basis": "QUALIFIED_DIRECTIONAL_MITIGATION_CYCLES_TELEMETRY_ONLY",
        "touch_authority": {
            "state": "TELEMETRY_ONLY",
            "changes_grade": False,
            "changes_risk": False,
            "changes_ranking": False,
            "changes_execution_eligibility": False,
            "changes_m1_authority": False,
        },
        "exhaustion_authority": {
            "state": "DISABLED_TOUCH_COUNT_NEVER_BLOCKS",
            "original_direction_new_execution": True,
            "m1_reacquisition": True,
            "context_visibility": True,
            "flip_monitoring": True,
            "flip_requires": "ACCEPTED_M15_INVALIDATION_THEN_RETEST_THEN_FRESH_M1_CONFIRMATION",
        },
        "grading_contract": {
            "TREND": "continuation-source structural quality; mitigation telemetry never changes grade",
            "COUNTERTREND": "HTF extremity + structural liquidity sweep/rejection + reversal-response quality; mitigation telemetry never changes grade",
        },
        "note": "Master Sniper base thesis risk is context x immutable analysis grade before entry-share/model multipliers. Touch/mitigation counts remain journal telemetry only. Only structural invalidation or a new analysis cycle may retire or replace a zone.",
    }


def classify_direction_context(direction: Direction, daily_context: Direction) -> str:
    if daily_context == Direction.NEUTRAL:
        return RISK_CONTEXT_TREND
    return RISK_CONTEXT_TREND if direction == daily_context else RISK_CONTEXT_COUNTERTREND
