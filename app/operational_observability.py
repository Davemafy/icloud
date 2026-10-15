"""Read-only operator clarity and strategy separation.

This module does not import the plan engine, MT5 execution, ownership mutation
or database writer. It must never turn a diagnostic into trade authorization.
"""
from __future__ import annotations

from typing import Any


# Ordered by execution relevance. These are descriptive display labels only.
_BLOCKERS = (
    ("late_stage_htf_reacquired", "CURRENT_HTF_ZONE_NOT_REACQUIRED",
     "The late-stage BUY/SELL thesis cannot authorize another entry until the current HTF zone is reacquired."),
    ("live_data_safe", "LIVE_DATA_OR_SPREAD_UNSAFE",
     "Fresh market data and spread safety are required."),
    ("m15_zone_healthy", "M15_ZONE_NOT_HEALTHY",
     "The current HTF zone has not passed M15 health."),
    ("m1_handoff_ready", "MACRO_HANDOFF_NOT_READY",
     "The historical thesis is not a current macro execution handoff."),
    ("fresh_m1_location_ready", "FRESH_M1_LOCATION_NOT_READY",
     "A current M1 entry location is required; old ownership cannot substitute for it."),
    ("target_ladder_phase_valid", "TARGET_LADDER_NOT_READY",
     "The current target ladder does not support a new entry."),
    ("grade_executable", "GRADE_NOT_EXECUTABLE",
     "The selected zone grade is not executable."),
    ("clear_run", "RUNWAY_NOT_READY",
     "The confirmed entry runway is not acceptable."),
    ("liquidity_in_marked_zone", "STRUCTURAL_LIQUIDITY_MISSING",
     "Required structural liquidity is missing from the selected zone."),
    ("two_plus_confluences", "INSUFFICIENT_CONFLUENCE",
     "The selected HTF zone lacks independent confluences."),
)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def institutional_decision_truth(journal: dict | None) -> dict:
    """Explain the first evidenced hold without asserting order permission."""
    j = _dict(journal)
    checks = _dict(j.get("checks"))
    debug = _dict(j.get("sequence_debug"))
    policy = _dict(j.get("execution_policy"))
    owner = _dict(policy.get("active_thesis"))
    zone = _dict(j.get("zone"))
    gate_stage = str(debug.get("gate_stage") or "UNKNOWN")
    gate_reason = str(debug.get("gate_reason") or "UNAVAILABLE")
    owner_id = str(owner.get("owner_zone_id") or "")
    locked = bool(owner.get("locked") and owner_id)
    owner_matches_zone = bool(locked and owner_id == str(zone.get("zone_id") or ""))

    if not zone:
        blocker = ("NO_SELECTED_ZONE", "No currently selected institutional trading zone.")
    elif debug.get("online") is not True:
        blocker = ("SEQUENCE_RUNTIME_UNVERIFIED", "No fresh Sequence EA execution-gate evidence.")
    else:
        blocker = None
        for check, code, explanation in _BLOCKERS:
            if checks.get(check) is False:
                blocker = code, explanation
                break
        if blocker is None:
            # Even an 11/11 prerequisite count is not permission to execute.
            blocker = ("AWAIT_SEQUENCE_ORDER_GATE",
                       "Prerequisites are not an M1 trigger. Follow the current Sequence gate and broker order result.")

    return {
        "read_only": True,
        "can_authorize_entry": False,
        "strategy": "INSTITUTIONAL_SMC",
        "historical_owner": {
            "locked": locked,
            "zone_id": owner_id or None,
            "matches_selected_zone": owner_matches_zone,
            "direction": owner.get("direction") or zone.get("direction") or "UNKNOWN",
            "lifecycle": owner.get("status") or "UNKNOWN",
            "is_fresh_entry_permission": False,
        },
        "fresh_entry": {
            "macro_handoff": bool(checks.get("m1_handoff_ready")),
            "current_htf_reacquired": bool(checks.get("late_stage_htf_reacquired")),
            "m1_location_ready": bool(checks.get("fresh_m1_location_ready")),
            "sequence_gate_stage": gate_stage,
            "sequence_gate_reason": gate_reason,
            "broker_order_authorized": "UNVERIFIED",
        },
        "primary_hold": {"code": blocker[0], "explanation": blocker[1]},
        "other_failed_prerequisites": [
            {"check": key, "code": code} for key, code, _ in _BLOCKERS if checks.get(key) is False
        ],
        "source": "CLOUD_JOURNAL_AND_SEQUENCE_TELEMETRY",
    }


def strategy_split_summary(institutional_performance: dict | None) -> dict:
    """Never attribute Sequence execution groups to standalone Session Sniper."""
    p = _dict(institutional_performance)
    return {
        "read_only": True,
        "paper_only": True,
        "institutional_smc": {
            "source": "EXISTING_INSTITUTIONAL_POSITION_JOURNAL",
            "status": "AVAILABLE" if p else "UNAVAILABLE",
            "execution_groups": p.get("execution_count"),
            "closed_groups": p.get("closed_executions"),
            "journal_records": p.get("trade_count"),
            "closed_journal_records": p.get("closed_trades"),
            "win_rate_pct": p.get("execution_win_rate", p.get("win_rate")),
            "net_demo_pnl": p.get("net_demo_pnl"),
            "by_setup": p.get("by_setup") or {},
            "by_grade": p.get("by_grade") or {},
        },
        "session_sniper": {
            "source": "STANDALONE_VPS_CSV_NOT_CONNECTED",
            "status": "NOT_CONNECTED",
            "execution_groups": None,
            "closed_groups": None,
            "win_rate_pct": None,
            "net_demo_pnl": None,
            "reason": "Standalone EA writes its own local research CSV. No authenticated Session Sniper journal ingestion is installed.",
        },
        "combined_account_risk": {
            "status": "NOT_VERIFIED",
            "enforcement_active": False,
            "estimated_exposure_pct": None,
            "reason": "Neither strategy's individual journal alone proves all-account live exposure. MT5 account-wide guard is not yet deployed.",
        },
    }


def operational_clarity(journal: dict | None, performance: dict | None) -> dict:
    return {
        "paper_only": True,
        "read_only": True,
        "decision": institutional_decision_truth(journal),
        "performance": strategy_split_summary(performance),
    }
