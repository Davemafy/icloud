from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_47_StrategicMultiModel_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def test_sequence_347_exposes_strategic_models_without_replacing_master_sniper_authority():
    text = _text()
    assert '#property version   "3.47"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.47"' in text
    assert "TZ47_BuildMomentumPullback" in text
    assert "TZ47_BuildVWAPReclaim" in text
    assert "TZ47_BuildOpeningRangeRetest" in text
    assert "TZ47_TryAlternativePrimary" in text
    assert "TZ47_TryAlternativeReentry" in text
    assert 'g_plan.setup_type!="CONTINUATION"' in text
    assert "!recentZone" in text


def test_strategic_model_enablement_is_cloud_and_local_regime_gated():
    text = _text()
    refresh = text[text.index("bool TZ31_RefreshCloudState"):text.index("void TZ_WriteSequenceState")]
    for needle in (
        'KV(text,"market_regime")',
        'TZ47_TextFlag(text,"model_momentum_pullback",false)',
        'TZ47_TextFlag(text,"model_vwap_proxy_reclaim",false)',
        'TZ47_TextFlag(text,"model_opening_range_retest",false)',
    ):
        assert needle in refresh

    regime = text[text.index("bool TZ47_RegimeAllows"):text.index("double TZ47_VWAP")]
    assert 'localRegime=="TREND"||localRegime=="EXPANSION"' in regime
    assert 'localRegime=="TREND"' in regime


def test_all_three_strategic_models_keep_structure_displacement_and_fresh_pd_array():
    text = _text()
    momentum = text[text.index("bool TZ47_BuildMomentumPullback"):text.index("bool TZ47_BuildVWAPReclaim")]
    vwap = text[text.index("bool TZ47_BuildVWAPReclaim"):text.index("int TZ47_DaysInMonth")]
    orb = text[text.index("bool TZ47_BuildORBSession"):text.index("bool TZ47_BuildOpeningRangeRetest")]

    for body in (momentum, vwap, orb):
        assert "StrongDisp" in body
        assert "FindFreshPD" in body
        assert "OlderPivot" in body

    assert "MomentumRetraceMin" in momentum and "MomentumRetraceMax" in momentum
    assert "TZ47_VWAP" in vwap
    assert "OpeningRangeMinutes" in orb and "ORBMinBreakATR" in orb


def test_strategic_primary_still_uses_universal_closed_m1_confirmation_and_zone_distal_stop():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    alt_at = evaluate.index("TZ47_TryAlternativePrimary")
    confirm_at = evaluate.index("TZ39_InitialEntryReady")
    stop_at = evaluate.index("TZ46_InitialZoneProtectedStop")
    rr_at = evaluate.index("TZ36_MinRRValid")
    size_at = evaluate.index("TZ37_LotsForRisk")
    send_at = evaluate.index("TZ37_SendOrders")
    assert alt_at < confirm_at < stop_at < rr_at < size_at < send_at
    assert "sig.reentry=false" in evaluate
    assert 'TZ_SetGate("TARGET","MIN_RR_NOT_MET")' in evaluate


def test_strategic_reentries_are_reduced_risk_and_keep_reentry_confirmation():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert "TZ47_TryAlternativeReentry" in evaluate
    assert "AlternativeModelRiskMultiplier" in evaluate
    assert "TZ35_ReentryEntryReady" in evaluate
    assert "AllProtected()" in evaluate


def test_sequence_347_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
