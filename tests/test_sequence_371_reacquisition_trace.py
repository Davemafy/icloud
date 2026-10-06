from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEQ = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_71_ReacquisitionTrace_Demo.mq5"
PREV = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_70_EngulfingRetest_Demo.mq5"
MAIN = ROOT / "app/main.py"
DASH = ROOT / "app/dashboard_view.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(text: str, signature: str) -> str:
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for idx in range(brace, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    raise AssertionError(f"unbalanced function: {signature}")


def test_371_version_and_reacquisition_inputs():
    text = _text(SEQ)
    assert '#property version   "3.71"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.71"' in text
    assert "input int ReacquisitionSweepWindowBars=90;" in text
    assert "input int ReacquisitionSweepToMssMaxBars=45;" in text


def test_371_p0_keeps_old_sweep_window_but_reentry_can_reconstruct_further_back():
    text = _text(SEQ)
    scan = _function_source(text, "bool TZ60_ScanPrimaryEngine(")
    assert "int requestedSweepBars=SweepWindowBars;" in scan
    assert (
        "if(reentry&&ReacquisitionSweepWindowBars>requestedSweepBars)"
        "requestedSweepBars=ReacquisitionSweepWindowBars;"
    ) in scan
    assert "int maxSweep=MathMin(requestedSweepBars,ArraySize(r)-12);" in scan
    # The extended window is not unconditional; P0 continues to use SweepWindowBars.
    assert "ReacquisitionSweepWindowBars" in scan
    assert "reentry&&ReacquisitionSweepWindowBars" in scan


def test_371_reconstructed_sweep_cannot_pair_with_unbounded_late_mss():
    text = _text(SEQ)
    scan = _function_source(text, "bool TZ60_ScanPrimaryEngine(")
    assert (
        "if(reentry&&ReacquisitionSweepToMssMaxBars>0&&"
        "(sw-j)>ReacquisitionSweepToMssMaxBars)break;"
    ) in scan
    # Existing downstream Model-1 contract is preserved.
    assert "TZ60_FindNearestMicroSwing" in scan
    assert "TZ60_FindAnyCausalPD" in scan
    assert "TZ60_FindRetestedCausalPD" in scan
    assert "TZ60_DirectionalClose(r[1],buy)" in scan


def test_371_sweep_rank_zero_has_explicit_forensic_reason_and_candidate():
    text = _text(SEQ)
    scan = _function_source(text, "bool TZ60_ScanPrimaryEngine(")
    assert 'g_tzTraceSweepRejectReason="NO_ZONE_CONTACT_IN_SWEEP_WINDOW"' in scan
    assert 'g_tzTraceSweepRejectReason="NO_MICRO_LIQUIDITY_LEVEL"' in scan
    assert 'g_tzTraceSweepRejectReason="SWEEP_BUFFER_NOT_CLEARED"' in scan
    assert "g_tzTraceSweepCandidateTs=r[sw].time;" in scan
    assert "g_tzTraceSweepCandidateLiquidity=liquidity;" in scan
    assert "g_tzTraceSweepCandidatePrice=sweepPrice;" in scan
    assert "g_tzTraceSweepCandidateClearancePoints=clearancePoints;" in scan


def test_371_heartbeat_carries_campaign_slot_and_pre_handoff_trace_truth():
    text = _text(SEQ)
    hb = _function_source(text, "void TZ_SendSequenceHeartbeat()")
    for field in (
        "opportunity_slot",
        "campaign_key",
        "trace_contact_ts",
        "trace_reconstructed_pre_handoff",
        "trace_sweep_scan_bars",
        "trace_sweep_reject_reason",
        "trace_sweep_candidate_ts",
        "trace_sweep_candidate_liquidity",
        "trace_sweep_candidate_price",
        "trace_sweep_candidate_clearance_points",
    ):
        assert field in hb


def test_371_cloud_and_dashboard_surface_reacquisition_truth():
    main = _text(MAIN)
    dash = _text(DASH)
    for field in (
        "opportunity_slot",
        "trace_sweep_scan_bars",
        "trace_sweep_reject_reason",
        "trace_sweep_candidate_ts",
        "trace_sweep_candidate_clearance_points",
    ):
        assert field in main
    assert "ZONE RE-ACQUISITION FORMING" in dash
    assert "Sweep candidate rejected:" in dash
    assert "Sequence 3.72+" in dash


def test_371_does_not_modify_trade_management_function():
    previous = _text(PREV)
    current = _text(SEQ)
    assert _function_source(current, "void ManagePositions()") == _function_source(
        previous, "void ManagePositions()"
    )


def test_371_reentry_cap_and_protected_swing_rr_gates_remain_mandatory():
    text = _text(SEQ)
    evaluate = _function_source(text, "void Evaluate()")
    assert "REENTRY_LIMIT_REACHED" in evaluate
    assert "MaxReentriesPerThesis" in evaluate
    assert "TZ69_ProtectedSwingExecutionStop" in evaluate
    assert "TZ36_MinRRValid" in evaluate
    assert evaluate.index("TZ69_ProtectedSwingExecutionStop") < evaluate.index("TZ36_MinRRValid")


def test_371_source_balanced():
    text = _text(SEQ)
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
