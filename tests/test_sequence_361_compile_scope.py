from pathlib import Path

SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_61_UnifiedEntryEngine_CompileFix_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def test_361_declares_primary_scan_state_inside_evaluate_scope():
    text = _text()
    start = text.index("void Evaluate()")
    end = text.index("\nint OnInit()", start)
    evaluate = text[start:end]
    assert 'string primaryStage="";bool primaryScanned=false;' in evaluate
    assert "TZ60_ScanPrimaryEngine(r,origBuy,false,recentZone,sig,sniperModel,primaryStage)" in evaluate
    assert "TZ60_ScanPrimaryEngine(r,origBuy,true,recentZone,sig,sniperModel,primaryStage)" in evaluate
    assert "if(primaryAuthority&&primaryScanned)stage=primaryStage;" in evaluate


def test_361_does_not_leak_primary_scan_state_into_accepted_flip_scope():
    text = _text()
    start = text.index("void TZ28_EvaluateAcceptedFlip()")
    end = text.index("\nvoid ", start + 10)
    block = text[start:end]
    assert "primaryStage" not in block
    assert "primaryScanned" not in block


def test_361_unified_engine_contract_is_unchanged():
    text = _text()
    assert '#property version   "3.61"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.61"' in text
    assert "TZ60_ScanPrimaryEngine" in text
    assert "TZ60_FindNearestMicroSwing" in text
    assert "TZ60_FindRetestedCausalPD" in text
    assert "TZ60_BuildEngulfing" in text
    assert "TZ46_InitialZoneProtectedStop" in text
    assert "TZ36_MinRRValid" in text


def test_361_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
