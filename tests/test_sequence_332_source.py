from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_32_ReleaseSafeOwner_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v332_release_clears_mt5_owner_mirror_tombstone_safely():
    text = _text()
    assert '#property version   "3.32"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.32"' in text
    start = text.index("void TZ30_SaveOwnerMirrorFromPlan")
    end = text.index("string TZ30_OwnerKV", start)
    fn = text[start:end]
    assert 'KV(text,"owner_mirror_active")!="1"' in fn
    assert 'FileDelete("TradeZone\\\\execution_owner_state.txt")' in fn
    assert "owner_mirror_zone_payload_b64" in fn


def test_v332_keeps_atomic_plan_authority_and_post_handoff_confirmation():
    text = _text()
    assert "TZ31_RefreshCloudState" in text
    assert "TZ31_BuildPostHandoffContinuation" in text
    assert 'g_tzExecutionAuthority=="HTF_ZONE_SWEEP_HANDOFF"' in text
    assert 'g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF"' in text
    assert 'KV(text,"execution_handoff_ts")' in text


def test_v332_preserves_no_chase_target_and_risk_guards():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    for needle in (
        "EntryAtValue(sig.buy,entry,sig,a)",
        "TZ_TargetDirectionValid(false,sig.buy,entry)",
        "LotsForRisk(entry,sl,risk)",
        "SIGNAL_FOUND_WAITING_FOR_PULLBACK",
        "MT5_ORDER_SEND_FAILED",
    ):
        assert needle in evaluate
