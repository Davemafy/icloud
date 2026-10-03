from pathlib import Path

SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_66_AcceptedInvalidationFlipAuthority_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def test_366_version_and_owner_invalidation_suspend_before_refresh():
    text = _text()
    assert '#property version   "3.66"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.66"' in text
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    invalidation = evaluate.index("if(M15Acceptance())")
    refresh = evaluate.index("TZ31_RefreshCloudState(false)")
    assert invalidation < refresh
    assert 'g_tzExecutionAuthority="NONE"' in evaluate
    assert 'TZ_SetGate("INVALIDATION_PENDING","M15_ACCEPTED_INVALIDATION_OWNER_SUSPENDED")' in evaluate


def test_366_routes_failed_owner_geometry_into_persisted_flip_evaluation():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    invalidation_block = evaluate[evaluate.index("if(M15Acceptance())"):evaluate.index("if(!TZ45_ActiveOwnerMatchesCurrentPlan())")]
    assert "TZ28_ArmAcceptedFlip();" in invalidation_block
    assert "if(g_tzFlipPlanStored)" in invalidation_block
    assert "TZ28_EvaluateAcceptedFlip();" in invalidation_block


def test_366_model3_rejects_opposite_direction_break():
    text = _text()
    start = text.index("bool TZ62_ConfirmBoundaryBreakout")
    end = text.index("\n}", start) + 2
    block = text[start:end]
    assert "oppositeBreak" in block
    assert 'stage="BREAKOUT_DIRECTION_CONFLICT"' in block
    assert "return false" in block
