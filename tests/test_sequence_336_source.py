from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_36_HandoffConfirmationRR_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v336_hardens_initial_post_handoff_entries():
    text = _text()
    assert '#property version   "3.36"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.36"' in text
    assert "PostHandoffRequireClosedM1ValueReaction=true" in text
    assert "TZ36_PostHandoffEntryReady" in text
    assert "WAITING_FOR_CLOSED_M1_POST_HANDOFF_VALUE_REACTION" in text
    assert 'bool postHandoff=(tag=="L0"||tag=="S0")' in text
    assert 'TZ_SetGate("HANDOFF_CONFIRMATION",handoffReason)' in text
    assert "POST_HANDOFF_PD_ACCEPTED_INVALIDATION" in text
    assert "POST_HANDOFF_SIGNAL_STALE" in text


def test_v336_enforces_target_expiry_and_minimum_rr_before_order():
    text = _text()
    assert "TZ36_NearestDirectionalTarget" in text
    assert "TZ36_TargetAlreadyTradedSinceHandoff" in text
    assert "POST_HANDOFF_OBJECTIVE_ALREADY_TRADED" in text
    assert "TZ36_MinRRValid" in text
    assert "required=MathMax(1.0,g_plan.min_rr)" in text
    assert 'TZ_SetGate("TARGET","MIN_RR_NOT_MET")' in text
    rr_pos = text.index('TZ_SetGate("TARGET","MIN_RR_NOT_MET")')
    send_pos = text.index("if(SendOrders(sig.buy,entry,sl,lots,false,tag,sig.pd_type))")
    assert rr_pos < send_pos


def test_v336_entry_audit_contains_rr_and_reaction_truth():
    text = _text()
    assert "TZ36_SendEntryDecisionAudit" in text
    for needle in [
        "nearest_open_target",
        "rr_at_entry",
        "min_rr_required",
        "closed_m1_value_reaction_required",
        "closed_m1_value_reaction_confirmed",
    ]:
        assert needle in text
    assert 'tag=="L0"?"LIQUIDITY_REVERSAL"' in text
