from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_37_GradeRiskAutoSize_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v337_grade_scaled_fixed_capital_risk_contract():
    text = _text()
    assert '#property version   "3.37"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.37"' in text
    assert "ResearchValidationInitialCapital=10000.0" in text
    assert "ResearchRiskPctAPlus=1.00" in text
    assert "ResearchRiskPctA=0.75" in text
    assert "ResearchRiskPctBPlus=0.25" in text
    assert "TZ37_DefaultGradeRiskPct" in text
    assert 'if(grade=="A+")return ResearchRiskPctAPlus;' in text
    assert 'if(grade=="A")return ResearchRiskPctA;' in text
    assert 'if(grade=="B+")return ResearchRiskPctBPlus;' in text
    assert "return MathMin(cap,bal);" in text
    assert "GRADE_SCALED_INITIAL_CAPITAL_V1" in text
    assert \'"risk_model\\":\\"%s\\"\' in text
    assert \'"grade_risk_pct\\":%.4f\' in text
    assert \'"risk_money\\":%.2f\' in text


def test_v337_lot_sizing_floors_and_never_rounds_subminimum_up():
    text = _text()
    assert "OrderCalcProfit(type,_Symbol,1.0,entry,sl,profit)" in text
    assert "TZ37_FloorVolume(money/perLot)" in text
    assert "if(out+1e-9<mn)return 0.0;" in text
    assert "LOT_SIZE_ZERO_OR_BELOW_MIN" in text
    assert "TZ37_SendOrders" in text
    assert "g_tzLastActualLots" in text
    assert "g_tzLastSplitPartial" in text


def test_v337_replaces_old_sizing_on_normal_and_flip_entries():
    text = _text()
    assert "TZ37_ThesisBudget(true,g_tzFlipPlan.grade)*share" in text
    assert "TZ37_LotsForRisk(sig.buy,entry,sl,risk)" in text
    assert "TZ37_SendOrders(sig.buy,entry,sl,lots,true,tag,sig.pd_type)" in text
    assert "TZ37_ThesisBudget(false,g_plan.grade)*share" in text
    assert "TZ37_SendOrders(sig.buy,entry,sl,lots,false,tag,sig.pd_type)" in text
    assert "double risk=ThesisBudget(true)*share" not in text
    assert "double risk=ThesisBudget(false)*share" not in text


def test_v337_preserves_confirmation_and_rr_guards_before_sizing():
    text = _text()
    for needle in [
        "TZ35_ReentryEntryReady",
        "TZ36_PostHandoffEntryReady",
        "TZ36_TargetAlreadyTradedSinceHandoff",
        "TZ36_MinRRValid",
        'TZ_SetGate("TARGET","MIN_RR_NOT_MET")',
    ]:
        assert needle in text
    rr_pos = text.index('TZ_SetGate("TARGET","MIN_RR_NOT_MET")')
    size_pos = text.index("TZ37_ThesisBudget(false,g_plan.grade)*share")
    send_pos = text.index("TZ37_SendOrders(sig.buy,entry,sl,lots,false,tag,sig.pd_type)")
    assert rr_pos < size_pos < send_pos
