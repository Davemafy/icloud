from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEQ = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_72_ExecutionContext_Demo.mq5"
PREV = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_71_ReacquisitionTrace_Demo.mq5"
MAIN = ROOT / "app/main.py"
DASH = ROOT / "app/dashboard_view.py"
STATIC = ROOT / "static/index.html"


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


def test_372_version_and_execution_context_contract():
    text = _text(SEQ)
    assert '#property version   "3.72"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.72"' in text
    for field in (
        "execution_context_type",
        "execution_context_analysis_id",
        "execution_context_zone_id",
        "execution_context_direction",
        "execution_context_source_zone_id",
        "execution_context_slot",
        "execution_context_contract_verified",
        "execution_context_contract_fingerprint",
        "execution_context_accepted_at",
        "execution_context_core_low",
        "execution_context_core_high",
        "execution_context_zone_low",
        "execution_context_zone_high",
        "execution_context_target1",
        "execution_context_target2",
        "execution_context_target3",
    ):
        assert field in text


def test_372_accepted_flip_context_uses_failed_zone_not_restored_current_map():
    text = _text(SEQ)
    fn = _function_source(text, "void TZ72_SetAcceptedFlipExecutionContext()")
    assert 'g_tzExecutionContextType="ACCEPTED_ZONE_FLIP"' in fn
    assert "g_tzExecutionContextAnalysis=g_tzFlipSourceAnalysis;" in fn
    assert "g_tzExecutionContextZone=g_tzFlipSourceZone;" in fn
    assert "g_tzExecutionContextDirection=g_tzFlipPlan.flip_direction;" in fn
    assert "g_tzExecutionContextAcceptedAt=g_tzFlipAcceptedAt;" in fn
    assert "g_tzExecutionContextContractVerified=g_tzFlipSniperContractVerified;" in fn
    assert "g_tzExecutionContextContractFingerprint=g_tzFlipSourceContractFingerprint;" in fn
    assert "g_tzExecutionContextTarget1=g_tzFlipPlan.flip_t1;" in fn
    assert "g_tzExecutionContextTarget2=g_tzFlipPlan.flip_t2;" in fn
    assert "g_tzExecutionContextTarget3=g_tzFlipPlan.flip_t3;" in fn


def test_372_flip_evaluation_sets_context_before_any_flip_gate():
    text = _text(SEQ)
    fn = _function_source(text, "void TZ28_EvaluateAcceptedFlip()")
    assert fn.index("TZ72_SetAcceptedFlipExecutionContext();") < fn.index("TZ28_FlipSafetyGuards()")


def test_372_normal_owner_and_map_contexts_remain_explicit():
    text = _text(SEQ)
    fn = _function_source(text, "void TZ72_SetPlanExecutionContext(bool ownerContext)")
    assert 'ownerContext?"THESIS_OWNER":"MAP_PLAN"' in fn
    assert "g_tzExecutionContextAnalysis=g_plan.analysis_id;" in fn
    assert "g_tzExecutionContextZone=g_plan.zone_id;" in fn
    assert "g_tzExecutionContextDirection=g_plan.original_direction;" in fn


def test_372_manage_positions_is_identical_to_371():
    assert _function_source(_text(SEQ), "void ManagePositions()") == _function_source(
        _text(PREV), "void ManagePositions()"
    )


def test_372_cloud_and_dashboard_surface_true_execution_source():
    main = _text(MAIN)
    dash = _text(DASH)
    static = _text(STATIC)
    for field in (
        "execution_context_type",
        "execution_context_zone_id",
        "execution_context_direction",
        "execution_context_slot",
        "execution_context_contract_verified",
        "execution_context_accepted_at",
    ):
        assert field in main
    assert "ACCEPTED-ZONE" in dash
    assert "Current journal/map selection" in dash
    assert "Mismatch detail:" in dash
    assert "Execution ACCEPTED-ZONE" in static
    assert "Execution source zone" in static
    assert "Flip target ladder" in static


def test_372_source_balanced():
    text = _text(SEQ)
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
