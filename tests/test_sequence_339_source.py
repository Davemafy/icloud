from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "mt5" / "stable" / "InstitutionalSMC_SequenceEA_v3_39_ProfessionalConfirmation_Demo.mq5"


def _text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_v339_requires_closed_m1_value_reaction_for_every_entry_family():
    text = _text()
    assert '#property version   "3.39"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.39"' in text
    assert "TZ39_ProfessionalValueReactionReady" in text
    assert "TZ39_InitialEntryReady" in text
    assert "TZ35_ReentryEntryReady" in text
    assert "TZ36_PostHandoffEntryReady" in text
    assert "TZ39_FlipEntryReady" in text

    # Initial primary families: sniper P0, deep/continuation C0, escape E0.
    evaluate = text[text.index("void Evaluate()"):text.index("int OnInit()", text.index("void Evaluate()"))]
    for tag in ['tag="P0"', 'tag="C0"', 'tag="E0"', 'tag="S0"', 'tag="L0"']:
        assert tag in evaluate
    assert "TZ39_InitialEntryReady" in evaluate
    assert "TZ35_ReentryEntryReady" in evaluate
    assert "TZ36_PostHandoffEntryReady" in evaluate
    assert 'TZ_SetGate("ENTRY_CONFIRMATION",entryReason)' in evaluate
    assert 'TZ_SetGate("REENTRY_CONFIRMATION",reentryReason)' in evaluate
    assert 'TZ_SetGate("HANDOFF_CONFIRMATION",handoffReason)' in evaluate
    assert "bool reactionRequired=true;" in evaluate

    # Direct value-touch entry permission has been removed from the active normal pipeline.
    assert "TZ_EntryAtEscapeValue(sig.buy,entry,sig,a)" not in evaluate

    flip = text[text.index("void TZ28_EvaluateAcceptedFlip()"):text.index("string TZ_JsonEscape", text.index("void TZ28_EvaluateAcceptedFlip()"))]
    assert 'tag="F0"' in flip
    assert '"FR"+IntegerToString' in flip
    assert "TZ39_FlipEntryReady" in flip
    assert 'TZ_SetGate("FLIP_CONFIRMATION",flipConfirmationReason)' in flip
    assert "if(!EntryAtValue(sig.buy,entry,sig,a))" not in flip


def test_v339_professional_confirmation_is_closed_directional_and_post_formation():
    text = _text()
    start = text.index("bool TZ39_ProfessionalValueReactionReady")
    end = text.index("bool TZ39_InitialEntryReady", start)
    gate = text[start:end]
    for needle in [
        "int newestAfterFormation=s.break_idx-1;",
        'if(StringFind(s.pd_type,"FVG")>=0)',
        "newestAfterFormation=MathMin(newestAfterFormation,s.pd_idx-2)",
        "bool touched=(r[i].high>=s.entry_low&&r[i].low<=s.entry_high)",
        "bool directional=buy?(r[i].close>r[i].open):(r[i].close<r[i].open)",
        "bool rejected=buy?(r[i].close>=s.entry_high):(r[i].close<=s.entry_low)",
        "bool microBreak=buy?(r[i].close>r[i+1].high):(r[i].close<r[i+1].low)",
        "directional&&rejected&&microBreak&&body>=a*minBodyATR",
        'reason=prefix+"_PD_ARRAY_ACCEPTED_INVALIDATION"',
        'reason=prefix+"_WAITING_FOR_CLOSED_M1_VALUE_REACTION"',
        'reason=prefix+"_VALUE_REACTION_CONFIRMED_BUT_CHASED"',
        'reason=prefix+"_CLOSED_M1_VALUE_REACTION_CONFIRMED"',
    ]:
        assert needle in gate


def test_v339_global_floor_can_only_harden_model_specific_confirmation():
    text = _text()
    assert "ProfessionalEntryValueReactionLookbackBars=6" in text
    assert "ProfessionalEntryReactionMinBodyATR=0.25" in text
    assert "ProfessionalEntryReactionMaxChaseATR=0.15" in text
    assert "MathMax(ReentryReactionMinBodyATR,ProfessionalEntryReactionMinBodyATR)" in text
    assert "MathMin(ReentryReactionMaxChaseATR,ProfessionalEntryReactionMaxChaseATR)" in text
    assert "MathMax(PostHandoffReactionMinBodyATR,ProfessionalEntryReactionMinBodyATR)" in text
    assert "MathMin(PostHandoffReactionMaxChaseATR,ProfessionalEntryReactionMaxChaseATR)" in text
    assert 'if(tag=="E0")maxChase=MathMin(maxChase,ResearchEscapeMaxChaseATR);' in text
    assert "if(!ReentryRequireClosedM1ValueReaction||!PostHandoffRequireClosedM1ValueReaction)return INIT_PARAMETERS_INCORRECT;" in text


def test_v339_preserves_context_grade_risk_and_structural_stop_contracts():
    text = _text()
    for needle in [
        "ResearchRiskPctTrendAPlus=1.00",
        "ResearchRiskPctTrendA=0.75",
        "ResearchRiskPctCountertrendAPlus=0.50",
        "ResearchRiskPctCountertrendA=0.25",
        "TZ38_ThesisBudget(false,g_plan.grade)*share",
        "TZ38_ThesisBudget(true,g_tzFlipPlan.grade)*share",
        "sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR",
        "TZ37_LotsForRisk",
        "OrderCalcProfit",
    ]:
        assert needle in text
