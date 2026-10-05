from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_69_ProtectedSwingStop_Demo.mq5")
MAIN = Path("app/main.py")
DASH = Path("app/dashboard_view.py")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_369_version_and_protected_swing_contract():
    text = _text(SEQ)
    assert '#property version   "3.69"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.69"' in text
    assert "bool TZ69_FindProtectedSwing(" in text
    assert "double TZ69_ProtectedSwingExecutionStop(" in text
    assert "ExecutionStopSwingLookbackBars=30" in text
    assert "M1_PROTECTED_SWING_HIGH" in text
    assert "M1_PROTECTED_SWING_LOW" in text


def test_369_swing_is_confirmed_adverse_and_still_protected():
    text = _text(SEQ)
    fn = text[text.index("bool TZ69_FindProtectedSwing("):text.index("double TZ69_ProtectedSwingExecutionStop(")]
    assert "for(int i=2;i<=finish;i++)" in fn
    assert "r[i].low<r[i-1].low && r[i].low<=r[i+1].low" in fn
    assert "r[i].high>r[i-1].high && r[i].high>=r[i+1].high" in fn
    assert "level<entry-tol" in fn
    assert "level>entry+tol" in fn
    assert "for(int j=i-1;j>=1;j--)" in fn
    assert "r[j].low<level-tol" in fn
    assert "r[j].high>level+tol" in fn
    assert "return true; // nearest in time among valid protected swings" in fn


def test_369_stop_is_swing_plus_buffer_not_generic_signal_anchor():
    text = _text(SEQ)
    stop = text[text.index("double TZ69_ProtectedSwingExecutionStop("):text.index("void TZ69_RecordCandidate(")]
    assert "TZ46_ZoneStopBuffer(m1Atr)" in stop
    assert "buy?(swingLevel-buffer):(swingLevel+buffer)" in stop

    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert "TZ69_ProtectedSwingExecutionStop(r,sig.buy,entry,a,stopSwingIdx,stopSwingLevel)" in evaluate
    assert "TZ68_M1ExecutionStop(sig.buy,sig.anchor_price,a)" not in evaluate
    assert 'TZ_SetGate("RISK","PROTECTED_M1_SWING_STOP_UNAVAILABLE")' in evaluate


def test_369_flip_uses_same_protected_swing_stop():
    text = _text(SEQ)
    flip = text[text.index("void TZ28_EvaluateAcceptedFlip()"):text.index("\nstring TZ_JsonEscape", text.index("void TZ28_EvaluateAcceptedFlip()"))]
    assert "TZ69_ProtectedSwingExecutionStop(r,sig.buy,entry,a,stopSwingIdx,stopSwingLevel)" in flip
    assert 'TZ_SetGate("RISK","FLIP_PROTECTED_M1_SWING_STOP_UNAVAILABLE")' in flip


def test_369_no_swing_is_fail_closed_and_rr_remains_after_stop_selection():
    text = _text(SEQ)
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    stop_at = evaluate.index("TZ69_ProtectedSwingExecutionStop")
    no_stop_at = evaluate.index("PROTECTED_M1_SWING_STOP_UNAVAILABLE")
    rr_at = evaluate.index("TZ36_MinRRValid")
    sizing_at = evaluate.index("TZ37_LotsForRisk")
    send_at = evaluate.index("TZ37_SendOrders")
    assert stop_at < no_stop_at < rr_at < sizing_at < send_at
    assert "MIN_RR_NOT_MET:RR=" in evaluate
    assert "SWING=%.2f" in evaluate


def test_369_swing_audit_is_published_to_cloud_and_dashboard():
    seq = _text(SEQ)
    main = _text(MAIN)
    dash = _text(DASH)
    for needle in ("last_candidate_swing_level", "last_candidate_swing_time"):
        assert needle in seq
        assert f'"{needle}"' in main
    assert "Candidate audit:" in dash
    assert "lastCandidateSwingLevel" in dash
    assert "lastCandidateSwingTime" in dash
    assert "nearest confirmed still-protected M1 swing" in dash


def test_369_source_is_structurally_balanced():
    text = _text(SEQ)
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
