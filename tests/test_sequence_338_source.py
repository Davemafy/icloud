from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "mt5" / "stable" / "InstitutionalSMC_SequenceEA_v3_38_ContextGradeRiskAutoSize_Demo.mq5"


def _text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_v338_context_grade_fixed_capital_risk_contract():
    text = _text()
    assert '#property version   "3.38"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.38"' in text
    assert "ResearchValidationInitialCapital=10000.0" in text
    assert "ResearchRiskPctTrendAPlus=1.00" in text
    assert "ResearchRiskPctTrendA=0.75" in text
    assert "ResearchRiskPctCountertrendAPlus=0.50" in text
    assert "ResearchRiskPctCountertrendA=0.25" in text
    assert 'if(grade=="A+")' in text
    assert 'if(grade=="A")' in text
    # v3.38 is retained as immutable historical evidence. B+ execution authority
    # was introduced in the later v3.41 release and must not be back-written here.
    assert 'if(grade!="A+"&&grade!="A")return 0.0;' in text
    assert "CONTEXT_GRADE_MATRIX_10000_V2" in text
    assert "TZ38_DefaultContextRiskPct" in text
    assert "TZ38_LoadRiskContract" in text
    assert "TZ38_ThesisBudget" in text
    assert "return MathMin(cap,bal);" in text


def test_v338_exports_original_and_flip_risk_truth():
    text = _text()
    for needle in [
        'KV(text,"risk_context")',
        'KV(text,"original_risk_pct")',
        'KV(text,"flip_risk_pct")',
        'FileWriteString(h,"risk_context="+g_tzRiskContext',
        'FileWriteString(h,"original_risk_pct="+DoubleToString(g_tzOriginalRiskPct,2)',
        'FileWriteString(h,"flip_risk_pct="+DoubleToString(g_tzFlipRiskPct,2)',
        'g_tzAcceptedFlipRiskPct',
        'flip_risk_pct="+DoubleToString(g_tzAcceptedFlipRiskPct,4)',
    ]:
        assert needle in text


def test_v338_preserves_proven_lot_sizing_and_order_cap():
    text = _text()
    assert "TZ37_LotsForRisk" in text
    assert "OrderCalcProfit" in text
    assert "TZ37_FloorVolume" in text
    assert "TZ37_SendOrders" in text
    assert "LOT_SIZE_ZERO_OR_BELOW_MIN" in text
    assert "TZ38_ThesisBudget(false,g_plan.grade)*share" in text
    assert "TZ38_ThesisBudget(true,g_tzFlipPlan.grade)*share" in text
    rr_pos = text.index('TZ_SetGate("TARGET","MIN_RR_NOT_MET")')
    size_pos = text.index("TZ38_ThesisBudget(false,g_plan.grade)*share")
    send_pos = text.index("TZ37_SendOrders(sig.buy,entry,sl,lots,false,tag,sig.pd_type)")
    assert rr_pos < size_pos < send_pos
