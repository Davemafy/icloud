from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_70_EngulfingRetest_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def test_370_version_and_model2_retest_family():
    text = _text()
    assert '#property version   "3.70"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.70"' in text
    assert "bool TZ70_BuildEngulfingRetest(" in text
    assert 'sig.pd_type="ZONE_ENGULFING_RETEST"' in text
    assert 'model="ZONE_ENGULFING_RETEST"' in text


def test_370_retest_requires_original_zone_engulfing_and_bounded_revisit():
    text = _text()
    fn = text[text.index("bool TZ70_BuildEngulfingRetest("):text.index("string TZ60_StageName", text.index("bool TZ70_BuildEngulfingRetest("))]
    assert "EngulfingRetestMaxBars" in fn
    assert "TZ62_FindZoneContactBeforeEvent" in fn
    assert "engLo<=prevLo+tol&&engHi>=prevHi-tol" in fn
    assert "TZ60_BarTouchesRange" in fn
    assert "EngulfingRetestConfirmBars" in fn


def test_370_retest_requires_fresh_closed_directional_rejection_and_no_chase():
    text = _text()
    fn = text[text.index("bool TZ70_BuildEngulfingRetest("):text.index("string TZ60_StageName", text.index("bool TZ70_BuildEngulfingRetest("))]
    assert "TZ60_DirectionalClose(r[1],buy)" in fn
    assert "r[1].close>=mid&&r[1].close>r[1].open" in fn
    assert "r[1].close<=mid&&r[1].close<r[1].open" in fn
    assert "EngulfingRetestMaxChaseATR" in fn
    assert 'stage="M2_ENGULFING_RETEST_CHASE_BLOCK"' in fn


def test_370_retest_is_model2_complete_without_model1_mss():
    text = _text()
    gate = text[text.index("bool TZ63_ModelSpecificConfirmationReady"):text.index("bool TZ62_BuildDisplacementContinuation")]
    assert 'sig.pd_type=="ZONE_ENGULFING"||sig.pd_type=="ZONE_ENGULFING_RETEST"' in gate
    assert "ENGULFING_MODEL_CONFIRMED_NO_SEPARATE_MSS_REQUIRED" in gate


def test_370_recovery_does_not_bypass_existing_thesis_entry_cap():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    limit = evaluate.index("REENTRY_LIMIT_REACHED")
    scan_after_limit = evaluate.index("TZ60_ScanPrimaryEngine", limit)
    assert limit < scan_after_limit
    assert 'tag="R"+IntegerToString(g_reentries+1)' in evaluate
    assert "g_reentries++" in evaluate
    assert "MaxReentriesPerThesis" in evaluate


def test_370_retest_keeps_protected_swing_stop_and_min_rr():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert 'sig.pd_type=="ZONE_ENGULFING_RETEST"' in evaluate
    assert "TZ69_ProtectedSwingExecutionStop(r,sig.buy,entry,a,stopSwingIdx,stopSwingLevel)" in evaluate
    assert "TZ36_MinRRValid(entry,sl,rrTarget,rr,rrRequired)" in evaluate
    assert evaluate.index("TZ69_ProtectedSwingExecutionStop") < evaluate.index("TZ36_MinRRValid")


def test_370_source_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
