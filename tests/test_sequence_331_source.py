from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_31_ExecutionPipeline_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v331_declares_atomic_execution_pipeline():
    text = _text()
    assert '#property version   "3.31"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.31"' in text
    assert "TZ31_RefreshCloudState" in text
    assert 'KV(text,"execution_handoff_ts")' in text
    assert "g_tzRuntimeThesisKey" in text


def test_v331_post_handoff_path_does_not_require_second_liquidity_sweep():
    text = _text()
    start = text.index("bool TZ31_BuildPostHandoffContinuation")
    end = text.index("string TZ31_DiagnosePostHandoff", start)
    fn = text[start:end]
    assert "StrongDisp" in fn
    assert "OlderPivot" in fn
    assert "FindFreshPD" in fn
    assert "OTE(" in fn
    assert "g_tzExecutionHandoffTs" in fn
    assert "HasInternalSweep" not in fn
    assert "TouchZone(" not in fn


def test_v331_sweep_and_liquidity_authorities_use_post_handoff_builder():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert 'g_tzExecutionAuthority=="HTF_ZONE_SWEEP_HANDOFF"' in evaluate
    assert 'g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF"' in evaluate
    assert evaluate.count("TZ31_BuildPostHandoffContinuation") >= 2
    assert 'g_tzExecutionAuthority=="HTF_CORE_HANDOFF"' in evaluate
    assert "BuildPrimary(r,a,origBuy,sig)" in evaluate


def test_v331_keeps_value_target_risk_and_no_chase_guards():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    for needle in (
        "EntryAtValue(sig.buy,entry,sig,a)",
        "TZ_TargetDirectionValid(false,sig.buy,entry)",
        "LotsForRisk(entry,sl,risk)",
        "MT5_ORDER_SEND_FAILED",
        "SIGNAL_FOUND_WAITING_FOR_PULLBACK",
    ):
        assert needle in evaluate


def test_v331_mirrors_exact_owner_payload_and_avoids_base_timer_double_fetch():
    text = _text()
    assert "owner_mirror_zone_payload_b64" in text
    timer = text[text.index("void OnTimer()"):text.index("\nvoid OnTick()", text.index("void OnTimer()"))]
    assert "TZ27_SeqCore_OnTimer" not in timer
    assert "TZ27_LoadExecutionAuthority" not in timer
    assert "TZ_PreCoreSync()" in timer
