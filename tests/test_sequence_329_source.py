from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_29_ZoneSweepOwnerFreeze_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v329_accepts_zone_sweep_as_normal_execution_authority():
    text = _text()
    assert '#property version   "3.29"' in text
    assert 'HTF_ZONE_SWEEP_HANDOFF' in text
    guards = text[text.index("bool TZ_ResearchGuards()"):text.index("bool TZ_TargetDirectionValid")]
    assert 'g_tzExecutionAuthority!="HTF_ZONE_SWEEP_HANDOFF"' in guards
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert 'g_tzExecutionAuthority=="HTF_ZONE_SWEEP_HANDOFF"' in evaluate
    assert "BuildPrimary(r,a,origBuy,sig)" in evaluate
    assert "BuildReentry(r,a,origBuy,sig)" in evaluate
    assert "TZ_BuildEscapePullback(r,a,origBuy,sig)" in evaluate


def test_v329_zone_sweep_authority_does_not_bypass_value_target_or_risk_guards():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    for needle in (
        "EntryAtValue(sig.buy,entry,sig,a)",
        "TZ_EntryAtEscapeValue(sig.buy,entry,sig,a)",
        "TZ_TargetDirectionValid(false,sig.buy,entry)",
        "LotsForRisk(entry,sl,risk)",
        "SPREAD_TOO_HIGH",
        "MT5_ORDER_SEND_FAILED",
    ):
        assert needle in text or needle in evaluate


def test_v329_preserves_accepted_zone_flip_ordering():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    arm = evaluate.index("TZ28_ArmAcceptedFlip();")
    refresh = evaluate.index("RefreshPlan();")
    research_guard = evaluate.index("TZ_ResearchGuards()")
    assert arm < refresh < research_guard
    assert 'ACCEPTED_ZONE_FLIP_HANDOFF' in text
    assert "BuildFlip(r,a,flipBuy,sig)" in text
