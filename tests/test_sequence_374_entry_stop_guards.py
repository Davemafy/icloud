from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEQ = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_74_EntryStopGuards_Demo.mq5"
PREV = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_73_ReentryFreshness_Demo.mq5"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(text: str, signature: str) -> str:
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for idx in range(brace, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    raise AssertionError(f"unbalanced function: {signature}")


def test_374_version_and_isolated_scope():
    text = _text(SEQ)
    assert '#property version   "3.74"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.74"' in text
    assert "TZ74_UniversalClosedM1DirectionalReady" in text
    assert "TZ74_PrimaryCoreProtectedExecutionStop" in text


def test_374_models_keep_their_existing_local_directional_close_contracts():
    text = _text(SEQ)
    engulf = _function_source(text, "bool TZ60_BuildEngulfing(")
    engulf_retest = _function_source(text, "bool TZ70_BuildEngulfingRetest(")
    model1 = _function_source(text, "bool TZ60_ScanPrimaryEngine(")
    breakout = _function_source(text, "bool TZ62_ConfirmBoundaryBreakout(")
    assert "TZ60_DirectionalClose(r[1],buy)" in engulf
    assert "TZ60_DirectionalClose(r[1],buy)" in engulf_retest
    assert "TZ60_DirectionalClose(r[1],buy)" in model1
    assert "TZ60_DirectionalClose(r[1],buy)" in breakout


def test_374_final_directional_gate_covers_model_1_2_3_and_p0_r1_r2():
    text = _text(SEQ)
    model = _function_source(text, "bool TZ74_IsSniperModel(")
    slot = _function_source(text, "bool TZ74_IsPrimaryOrReentrySniperSlot(")
    gate = _function_source(text, "bool TZ74_UniversalClosedM1DirectionalReady(")
    assert 'StringFind(sig.pd_type,"MASTER_SNIPER_PD_")==0' in model
    assert 'sig.pd_type=="ZONE_ENGULFING"' in model
    assert 'sig.pd_type=="ZONE_ENGULFING_RETEST"' in model
    assert 'StringFind(sig.pd_type,"BREAKOUT_")==0' in model
    for tag in ('tag=="P0"', 'tag=="B0"', 'tag=="R1"', 'tag=="R2"'):
        assert tag in slot
    assert "confirmIdx=1" in gate
    assert "TZ60_DirectionalClose(r[1],buy)" in gate
    assert "WAITING_FOR_UNIVERSAL_CLOSED_M1_DIRECTIONAL_CONFIRMATION" in gate


def test_374_final_directional_gate_is_downstream_of_model_confirmation_and_before_order_qualification():
    text = _text(SEQ)
    evaluate = _function_source(text, "void Evaluate()")
    sig_valid = evaluate.index("if(!sig.valid)")
    model_confirm = evaluate.index("TZ63_ModelSpecificConfirmationReady", sig_valid)
    universal = evaluate.index("TZ74_UniversalClosedM1DirectionalReady", model_confirm)
    orderflow = evaluate.index("TZ67_EvaluateOrderFlowProxy", universal)
    entry = evaluate.index("double entry=sig.buy?tk.ask:tk.bid;", orderflow)
    stop = evaluate.index("TZ69_ProtectedSwingExecutionStop", entry)
    send = evaluate.index("TZ37_SendOrders", stop)
    assert sig_valid < model_confirm < universal < orderflow < entry < stop < send


def test_374_p0_stop_requires_m1_swing_then_respects_core_geometry_without_fixed_new_buffer():
    text = _text(SEQ)
    fn = _function_source(text, "double TZ74_PrimaryCoreProtectedExecutionStop(")
    evaluate = _function_source(text, "void Evaluate()")
    assert 'tag=="P0"||tag=="B0"' in fn
    assert "g_plan.core_low" in fn
    assert "g_plan.core_high" in fn
    assert "TZ46_ZoneStopBuffer(m1Atr)" in fn
    assert "MathMin(microStop,coreStop)" in fn
    assert "MathMax(microStop,coreStop)" in fn
    assert "P0_M1_SWING_PLUS_CORE_LOW" in fn
    assert "P0_M1_SWING_PLUS_CORE_HIGH" in fn
    protected = evaluate.index("microSl=TZ69_ProtectedSwingExecutionStop")
    core = evaluate.index("TZ74_PrimaryCoreProtectedExecutionStop", protected)
    rr = evaluate.index("TZ36_MinRRValid", core)
    assert protected < core < rr


def test_374_r1_r2_stop_contract_is_not_widened_by_core_geometry():
    text = _text(SEQ)
    fn = _function_source(text, "double TZ74_PrimaryCoreProtectedExecutionStop(")
    assert 'if(!(tag=="P0"||tag=="B0")||!TZ74_IsSniperModel(sig))' in fn
    assert "return microStop;" in fn


def test_374_no_implicit_inside_core_exception_is_invented():
    text = _text(SEQ)
    fn = _function_source(text, "double TZ74_PrimaryCoreProtectedExecutionStop(")
    assert "no implicit exception is guessed here" in fn
    assert "interior-core structural" in fn


def test_374_entry_audit_records_closed_m1_direction_candle_proof():
    text = _text(SEQ)
    audit = _function_source(text, "void TZ36_SendEntryDecisionAudit(")
    for field in (
        "closed_m1_direction_bar_ts",
        "closed_m1_direction_open",
        "closed_m1_direction_high",
        "closed_m1_direction_low",
        "closed_m1_direction_close",
        "closed_m1_direction_ok",
    ):
        assert field in audit
    assert "TZ60_DirectionalClose(r[1],s.buy)" in audit


def test_374_accepted_flip_and_trade_management_are_unchanged():
    previous = _text(PREV)
    current = _text(SEQ)
    assert _function_source(current, "void TZ28_EvaluateAcceptedFlip()") == _function_source(
        previous, "void TZ28_EvaluateAcceptedFlip()"
    )
    assert _function_source(current, "void ManagePositions()") == _function_source(
        previous, "void ManagePositions()"
    )


def test_374_source_balanced():
    text = _text(SEQ)
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
