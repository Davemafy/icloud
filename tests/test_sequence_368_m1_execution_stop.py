from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_68_M1ExecutionStop_Demo.mq5")
MAIN = Path("app/main.py")
DASH = Path("app/dashboard_view.py")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_368_version_and_execution_stop_contract():
    text = _text(SEQ)
    assert '#property version   "3.68"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.68"' in text
    assert "double TZ68_M1ExecutionStop(bool buy,double anchor,double m1Atr)" in text
    assert "double buffer=TZ46_ZoneStopBuffer(m1Atr);" in text
    assert "double out=buy?(anchor-buffer):(anchor+buffer);" in text
    assert "M1_CAUSAL_STRUCTURE" in text
    assert "HTF distal boundary remains thesis invalidation only" in text


def test_368_confirmed_entries_use_m1_stop_before_rr_and_sizing():
    text = _text(SEQ)
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    stop_at = evaluate.index("TZ68_M1ExecutionStop")
    rr_at = evaluate.index("TZ36_MinRRValid")
    sizing_at = evaluate.index("TZ37_LotsForRisk")
    send_at = evaluate.index("TZ37_SendOrders")
    assert stop_at < rr_at < sizing_at < send_at
    assert "TZ46_InitialZoneProtectedStop(sig.buy,microSl,g_plan.zone_low,g_plan.zone_high,a)" not in evaluate
    assert 'TZ_SetGate("RISK","M1_EXECUTION_STOP_UNAVAILABLE")' in evaluate


def test_368_accepted_flip_uses_causal_m1_stop():
    text = _text(SEQ)
    flip = text[text.index("void TZ28_EvaluateAcceptedFlip()"):text.index("\nstring TZ_JsonEscape", text.index("void TZ28_EvaluateAcceptedFlip()"))]
    assert "TZ68_M1ExecutionStop(sig.buy,sig.anchor_price,a)" in flip
    assert "TZ46_InitialZoneProtectedStop(sig.buy,microSl,g_tzFlipPlan.zone_low,g_tzFlipPlan.zone_high,a)" not in flip
    assert 'TZ_SetGate("RISK","FLIP_M1_EXECUTION_STOP_UNAVAILABLE")' in flip


def test_368_min_rr_remains_fail_closed_but_is_transparent():
    text = _text(SEQ)
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert "bool rrOk=TZ36_MinRRValid(entry,sl,rrTarget,rr,rrRequired);" in evaluate
    assert "TZ68_RecordCandidate(entry,sl,rrTarget,rr,rrRequired,g_tzLastCandidateStopBasis);" in evaluate
    assert "MIN_RR_NOT_MET:RR=" in evaluate
    assert "REQ=" in evaluate
    assert "STOP=%s" in evaluate


def test_368_state_heartbeat_cloud_and_dashboard_publish_rr_audit():
    seq = _text(SEQ)
    main = _text(MAIN)
    dash = _text(DASH)
    for needle in (
        "last_candidate_entry",
        "last_candidate_stop",
        "last_candidate_target",
        "last_candidate_rr",
        "last_candidate_rr_required",
        "last_candidate_stop_basis",
    ):
        assert needle in seq
        assert f'"{needle}"' in main
    assert "Candidate audit:" in dash
    assert "confirmed execution SL" in dash
    assert "separates M1 trade invalidation from the wider HTF thesis invalidation" in dash


def test_368_source_is_structurally_balanced():
    text = _text(SEQ)
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
