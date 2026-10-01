from pathlib import Path

SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_63_ModelSpecificSniperConfirmation_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def _evaluate(text: str) -> str:
    start = text.index("void Evaluate()")
    return text[start:text.index("\nint OnInit()", start)]


def test_363_version_and_model_specific_contract():
    text = _text()
    assert '#property version   "3.63"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.63"' in text
    assert "TZ63_ModelSpecificConfirmationReady" in text
    assert "TZ62_UniversalM1ShiftReady" not in text
    assert "ENGULFING_WAITING_FOR_M1_MICRO_STRUCTURE_SHIFT" not in text
    assert 'stage="BREAKOUT_M1_MICRO_SHIFT"' not in text


def test_363_model1_keeps_closed_m1_micro_shift():
    text = _text()
    scan = text[text.index("bool TZ60_ScanPrimaryEngine"):text.index("bool TZ62_FindPostEventMicroShift")]
    assert 'if(!TZ60_FindMicroMSS' in scan or "M1_MICRO_MSS" in scan
    assert "causal" in scan.lower()
    assert "TZ60_FindRetestedCausalPD" in scan
    gate = text[text.index("bool TZ63_ModelSpecificConfirmationReady"):text.index("bool TZ62_BuildDisplacementContinuation")]
    assert "WAITING_FOR_M1_MICRO_STRUCTURE_SHIFT" in gate
    assert "M1_MICRO_STRUCTURE_SHIFT_CONFIRMED" in gate


def test_363_model2_engulfing_has_no_separate_mss_gate():
    text = _text()
    build = text[text.index("bool TZ60_BuildEngulfing"):text.index("string TZ60_StageName")]
    assert 'sig.pd_type="ZONE_ENGULFING"' in build
    gate = text[text.index("bool TZ63_ModelSpecificConfirmationReady"):text.index("bool TZ62_BuildDisplacementContinuation")]
    assert 'if(sig.pd_type=="ZONE_ENGULFING")' in gate
    assert "ENGULFING_MODEL_CONFIRMED_NO_SEPARATE_MSS_REQUIRED" in gate
    engulf_branch = gate[gate.index('if(sig.pd_type=="ZONE_ENGULFING")'):gate.index("// Model 3")]
    assert "TZ62_FindPostEventMicroShift" not in engulf_branch


def test_363_model3_breakout_requires_break_acceptance_retest_directional_close_not_mss():
    text = _text()
    block = text[text.index("bool TZ62_ConfirmBoundaryBreakout"):text.index("bool TZ62_TryOpeningRangeBreakout")]
    for needle in (
        "StrongDisp",
        'stage="BREAKOUT_ACCEPTANCE"',
        'stage="BREAKOUT_RETEST"',
        'stage="BREAKOUT_DIRECTIONAL_CLOSE"',
        'stage="BREAKOUT_NO_CHASE"',
        'sig.pd_type="BREAKOUT_"+source+"_"+pt',
    ):
        assert needle in block
    assert "TZ62_FindPostEventMicroShift" not in block
    assert 'stage="BREAKOUT_M1_MICRO_SHIFT"' not in block
    assert "sig.break_idx=br" in block
    assert "sig.break_level=boundary" in block


def test_363_primary_and_flip_paths_use_model_specific_gate():
    text = _text()
    evaluate = _evaluate(text)
    assert "TZ63_ModelSpecificConfirmationReady(r,sig.buy,sig" in evaluate
    flip_start = text.index("void TZ28_EvaluateAcceptedFlip()")
    flip = text[flip_start:text.index("\nstring TZ_JsonEscape", flip_start)]
    assert "TZ63_ModelSpecificConfirmationReady(r,sig.buy,sig" in flip


def test_363_trade_management_wiring_is_unchanged():
    text = _text()
    assert "#define ManagePositions TZ21_BaseManagePositions" in text
    assert "TZ_PreCoreSync();ManagePositions();Evaluate();" in text


def test_363_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
