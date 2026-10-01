from pathlib import Path

SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_62_ComprehensiveEntryEngineRepair_Demo.mq5")

def _text() -> str:
    return SEQ.read_text(encoding="utf-8")

def _evaluate(text: str) -> str:
    start = text.index("void Evaluate()")
    return text[start:text.index("\nint OnInit()", start)]

def test_362_version_and_contract():
    text = _text()
    assert '#property version   "3.62"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.62"' in text
    for needle in (
        "TZ62_UniversalM1ShiftReady",
        "TZ62_BuildDisplacementContinuation",
        "TZ62_BuildInstitutionalBreakout",
        "TZ62_ConfirmBoundaryBreakout",
        "TZ62_FindZoneContactBeforeEvent",
        "owner_mirror_campaign_key",
        "trace_reconstructed_pre_handoff",
    ):
        assert needle in text

def test_362_m1_shift_is_universal():
    text = _text()
    evaluate = _evaluate(text)
    assert "TZ62_UniversalM1ShiftReady(r,sig.buy,sig" in evaluate
    flip = text[text.index("void TZ28_EvaluateAcceptedFlip()"):text.index("\nstring TZ_JsonEscape", text.index("void TZ28_EvaluateAcceptedFlip()"))]
    assert "TZ62_UniversalM1ShiftReady(r,sig.buy,sig" in flip
    universal = text[text.index("bool TZ62_UniversalM1ShiftReady"):text.index("bool TZ62_BuildDisplacementContinuation")]
    assert "ENGULFING_WAITING_FOR_M1_MICRO_STRUCTURE_SHIFT" in universal
    assert "WAITING_FOR_M1_MICRO_STRUCTURE_SHIFT" in universal

def test_362_reconstructs_contact_before_sweep():
    text = _text()
    scan = text[text.index("bool TZ60_ScanPrimaryEngine"):text.index("bool TZ62_FindPostEventMicroShift")]
    assert "TZ62_FindZoneContactBeforeEvent(r,sw,SniperContactLeadBars,contact)" in scan
    assert "if(!TouchZone(r[sw]))continue;" not in scan
    assert "g_tzTraceContactTs=r[contact].time" in scan

def test_362_reentry_priority_is_zone_then_continuation_then_breakout():
    evaluate = _evaluate(_text())
    a = evaluate.index("TZ60_ScanPrimaryEngine(r,origBuy,true,recentZone")
    b = evaluate.index("TZ62_BuildDisplacementContinuation")
    c = evaluate.index("TZ62_BuildInstitutionalBreakout", b)
    assert a < b < c
    assert 'g_tzCandidateModel="DISPLACEMENT_CONTINUATION"' in evaluate
    assert 'g_tzCandidateModel="INSTITUTIONAL_BREAKOUT"' in evaluate

def test_362_breakout_contract():
    text = _text()
    block = text[text.index("bool TZ62_ConfirmBoundaryBreakout"):text.index("bool TZ62_TryOpeningRangeBreakout")]
    for needle in (
        "StrongDisp",
        'stage="BREAKOUT_ACCEPTANCE"',
        'stage="BREAKOUT_RETEST"',
        "TZ62_FindPostEventMicroShift",
        'stage="BREAKOUT_M1_MICRO_SHIFT"',
        'stage="BREAKOUT_NO_CHASE"',
        'sig.pd_type="BREAKOUT_"+source+"_"+pt',
    ):
        assert needle in block
    assert "TZ62_TryOpeningRangeBreakout" in text
    assert "TZ62_BuildCompressionBreakout" in text
    assert '"M1_BALANCE"' in text

def test_362_trade_management_wiring_is_unchanged():
    text = _text()
    assert "#define ManagePositions TZ21_BaseManagePositions" in text
    assert "TZ_PreCoreSync();ManagePositions();Evaluate();" in text

def test_362_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
