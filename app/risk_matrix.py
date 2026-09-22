from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .models import Direction, Grade, Zone

RISK_MODEL = "CONTEXT_GRADE_MATRIX_10000_V2"
RISK_CONTEXT_TREND = "TREND"
RISK_CONTEXT_COUNTERTREND = "COUNTERTREND"

# Professional research contract:
# - TREND and COUNTERTREND use different structural qualification models;
# - the resulting A+/A label then maps to the context-specific risk budget below;
# - B+ remains visible research context but cannot acquire NEW execution authority.
EXECUTION_GRADES = {Grade.A_PLUS, Grade.A}


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
    return 0.0


def original_risk_pct(zone: Zone) -> float:
    return risk_pct_for_grade(zone.grade, zone_risk_context(zone))


def flip_risk_pct(zone: Zone) -> float:
    return risk_pct_for_grade(zone.grade, opposite_risk_context(zone_risk_context(zone)))


def execution_touch_limit(zone: Zone) -> int:
    # A+ is kept very fresh. A may remain research-executable through a second
    # qualified mitigation. B+ is context only and therefore has no touch quota.
    if zone.grade == Grade.A_PLUS:
        return 1
    if zone.grade == Grade.A:
        return 2
    return -1


def execution_grade_eligible(zone: Zone) -> bool:
    return zone.grade in EXECUTION_GRADES and execution_touch_limit(zone) >= int(zone.touch_count)


def matrix_payload() -> dict[str, Any]:
    return {
        "model": RISK_MODEL,
        "validation_initial_capital": float(SETTINGS.research_validation_initial_capital),
        "compounding": False,
        "risk_base_rule": "MIN_VALIDATION_CAPITAL_OR_LIVE_BALANCE",
        "trend": {
            "A+": float(SETTINGS.research_risk_pct_trend_a_plus),
            "A": float(SETTINGS.research_risk_pct_trend_a),
        },
        "countertrend": {
            "A+": float(SETTINGS.research_risk_pct_countertrend_a_plus),
            "A": float(SETTINGS.research_risk_pct_countertrend_a),
        },
        "B+": 0.0,
        "bplus_execution_authority": False,
        "touch_limits": {"A+": 1, "A": 2, "B+": 0},
        "grading_contract": {
            "TREND": "continuation-source strength + freshness",
            "COUNTERTREND": "HTF extremity + structural liquidity sweep/rejection + reversal-response quality",
        },
        "note": "Base thesis risk is context x grade before entry-share and model-specific multipliers.",
    }


def classify_direction_context(direction: Direction, daily_context: Direction) -> str:
    if daily_context == Direction.NEUTRAL:
        return RISK_CONTEXT_TREND
    return RISK_CONTEXT_TREND if direction == daily_context else RISK_CONTEXT_COUNTERTREND
