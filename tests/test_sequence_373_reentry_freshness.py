from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEQ = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_73_ReentryFreshness_Demo.mq5"
PREV = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_72_ExecutionContext_Demo.mq5"
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


def test_373_version_and_reentry_deterioration_guard():
    text = _text(SEQ)
    assert '#property version   "3.73"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.73"' in text
    assert "TZ73_ReentryFreshEpochValid" in text
    assert "TZ73_OriginalZoneReentryLocationValid" in text
    assert "REENTRY_FRESHNESS" in text
    assert "REENTRY_LOCATION" in text


def test_373_each_reentry_requires_new_anchor_and_break_after_prior_entry():
    text = _text(SEQ)
    fn = _function_source(text, "bool TZ73_ReentryFreshEpochValid(")
    assert "g_lastTradeBar<=0" in fn
    assert "anchorTs<=g_lastTradeBar||breakTs<=g_lastTradeBar" in fn
    assert "REENTRY_PREVIOUS_EPOCH_EVENT" in fn
    assert "REENTRY_FRESH_POST_PRIOR_ENTRY_EVENT" in fn


def test_373_original_zone_reentry_requires_fresh_zone_contact_epoch():
    text = _text(SEQ)
    fn = _function_source(text, "bool TZ73_ReentryFreshEpochValid(")
    assert "TZ73_OriginalZoneReentryFamily(sig)" in fn
    assert "g_tzTraceContactTs<=0||g_tzTraceContactTs<=g_lastTradeBar" in fn
    assert "REENTRY_ZONE_CONTACT_PREVIOUS_EPOCH" in fn


def test_373_distal_side_guard_is_limited_to_original_zone_reacquisition_family():
    text = _text(SEQ)
    family = _function_source(text, "bool TZ73_OriginalZoneReentryFamily(")
    location = _function_source(text, "bool TZ73_OriginalZoneReentryLocationValid(")
    assert 'StringFind(sig.pd_type,"MASTER_SNIPER_PD_")==0' in family
    assert 'sig.pd_type=="ZONE_ENGULFING"' in family
    assert 'sig.pd_type=="ZONE_ENGULFING_RETEST"' in family
    # Fresh continuation/breakout families are intentionally NOT classified as
    # original-zone reacquisition, so they retain their existing contracts.
    assert "CONTINUATION_PD_" not in family
    assert "BREAKOUT_" not in family
    assert "g_plan.zone_low" in location
    assert "g_plan.zone_high" in location
    assert "REENTRY_ORIGINAL_ZONE_MODEL_BEYOND_DISTAL_BOUNDARY" in location


def test_373_guards_run_only_after_a_reentry_signal_exists():
    text = _text(SEQ)
    evaluate = _function_source(text, "void Evaluate()")
    sig_valid = evaluate.index("if(!sig.valid)")
    freshness = evaluate.index("TZ73_ReentryFreshEpochValid", sig_valid)
    model_confirm = evaluate.index("TZ63_ModelSpecificConfirmationReady", freshness)
    entry = evaluate.index("double entry=sig.buy?tk.ask:tk.bid;", model_confirm)
    location = evaluate.index("TZ73_OriginalZoneReentryLocationValid", entry)
    stop = evaluate.index("TZ69_ProtectedSwingExecutionStop", location)
    assert sig_valid < freshness < model_confirm < entry < location < stop


def test_373_p0_scanner_and_accepted_flip_logic_are_unchanged_from_372():
    previous = _text(PREV)
    current = _text(SEQ)
    assert _function_source(current, "bool TZ60_ScanPrimaryEngine(") == _function_source(
        previous, "bool TZ60_ScanPrimaryEngine("
    )
    assert _function_source(current, "void TZ28_EvaluateAcceptedFlip()") == _function_source(
        previous, "void TZ28_EvaluateAcceptedFlip()"
    )


def test_373_trade_management_is_byte_for_byte_unchanged_from_372():
    assert _function_source(_text(SEQ), "void ManagePositions()") == _function_source(
        _text(PREV), "void ManagePositions()"
    )


def test_373_existing_cap_stop_rr_and_continuation_paths_remain_present():
    text = _text(SEQ)
    evaluate = _function_source(text, "void Evaluate()")
    assert "REENTRY_LIMIT_REACHED" in evaluate
    assert "MaxReentriesPerThesis" in evaluate
    assert "TZ62_BuildDisplacementContinuation" in evaluate
    assert "TZ62_BuildInstitutionalBreakout" in evaluate
    assert "TZ69_ProtectedSwingExecutionStop" in evaluate
    assert "TZ36_MinRRValid" in evaluate


def test_373_cloud_dashboard_explain_new_holds():
    main = _text(MAIN)
    dash = _text(DASH)
    assert 'stage in {"REENTRY_FRESHNESS", "REENTRY_LOCATION"}' in main
    assert '"REENTRY HOLD"' in main
    assert "RE-ENTRY BLOCKED: STALE PRIOR EPOCH" in dash
    assert "RE-ENTRY BLOCKED: BEYOND DISTAL BOUNDARY" in dash
    assert "Sequence 3.73+" in dash


def test_373_source_balanced():
    text = _text(SEQ)
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
