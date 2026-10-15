from app.operational_observability import (
    institutional_decision_truth, strategy_split_summary, operational_clarity,
)


def _case():
    return {
        "zone": {"zone_id": "B1", "direction": "BUY"},
        "checks": {
            "m1_handoff_ready": True,
            "late_stage_htf_reacquired": False,
            "fresh_m1_location_ready": True,
            "live_data_safe": True,
        },
        "execution_policy": {"active_thesis": {
            "locked": True, "owner_zone_id": "B1", "direction": "BUY",
            "status": "OBJECTIVE_IN_PROGRESS",
        }},
        "sequence_debug": {
            "online": True, "gate_stage": "DISPLACEMENT",
            "gate_reason": "M1_CONFIRMATION_PENDING",
        },
    }


def test_historical_owner_is_never_new_entry_authority():
    view = institutional_decision_truth(_case())
    assert view["historical_owner"]["locked"] is True
    assert view["historical_owner"]["matches_selected_zone"] is True
    assert view["historical_owner"]["is_fresh_entry_permission"] is False
    assert view["fresh_entry"]["current_htf_reacquired"] is False
    assert view["primary_hold"]["code"] == "CURRENT_HTF_ZONE_NOT_REACQUIRED"
    assert view["can_authorize_entry"] is False


def test_all_prerequisites_still_cannot_authorize_order():
    case = _case()
    case["checks"]["late_stage_htf_reacquired"] = True
    assert institutional_decision_truth(case)["primary_hold"]["code"] == "AWAIT_SEQUENCE_ORDER_GATE"


def test_unverified_sequence_must_not_be_painted_as_ready():
    case = _case()
    case["sequence_debug"]["online"] = False
    assert institutional_decision_truth(case)["primary_hold"]["code"] == "SEQUENCE_RUNTIME_UNVERIFIED"


def test_unavailable_or_partial_journal_does_not_crash():
    assert institutional_decision_truth({})["primary_hold"]["code"] == "NO_SELECTED_ZONE"
    assert operational_clarity(None, None)["performance"]["session_sniper"]["net_demo_pnl"] is None


def test_no_synthetic_session_sniper_or_combined_risk():
    p = strategy_split_summary({"execution_count": 51, "net_demo_pnl": -43.36})
    assert p["institutional_smc"]["execution_groups"] == 51
    assert p["session_sniper"]["execution_groups"] is None
    assert p["session_sniper"]["status"] == "NOT_CONNECTED"
    assert p["combined_account_risk"]["enforcement_active"] is False


def test_unverified_grouping_is_never_claimed():
    p = strategy_split_summary({"trade_count": 67, "closed_trades": 67})
    assert p["institutional_smc"]["execution_groups"] is None
    assert p["institutional_smc"]["journal_records"] == 67
