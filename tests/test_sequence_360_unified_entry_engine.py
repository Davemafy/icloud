from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_60_UnifiedEntryEngine_Demo.mq5")
BRIDGE = Path("mt5/stable/InstitutionalSMC_DataBridge_v1_58_EntryRunwayTruth.mq5")


def _text(path: Path = SEQ) -> str:
    return path.read_text(encoding="utf-8")


def _evaluate(text: str) -> str:
    start = text.index("void Evaluate()")
    return text[start:text.index("\nint OnInit()", start)]


def test_360_is_one_primary_scanner_for_execution_and_diagnostics():
    text = _text()
    evaluate = _evaluate(text)
    assert '#property version   "3.60"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.60"' in text
    assert "TZ60_ScanPrimaryEngine" in text
    assert evaluate.count("TZ60_ScanPrimaryEngine") == 2  # P0 and R1/R2
    assert "TZ50_TrySniperModels" not in evaluate
    assert "TZ50_DiagnoseSniper" not in evaluate
    assert "primaryStage" in evaluate


def test_360_uses_micro_liquidity_and_wick_sweep_not_closeback():
    text = _text()
    scan = text[text.index("bool TZ60_ScanPrimaryEngine"):text.index("\nvoid TZ_ShallowValue", text.index("bool TZ60_ScanPrimaryEngine"))]
    assert "TZ60_FindNearestMicroSwing(r,sw,!buy,microDepth,li,liquidity)" in scan
    assert "TZ60_FindNearestMicroSwing(r,sw,buy,microDepth,ms,mss)" in scan
    assert "r[sw].low<liquidity-buf" in scan
    assert "r[sw].high>liquidity+buf" in scan
    assert "r[sw].close>liquidity" not in scan
    assert "r[sw].close<liquidity" not in scan


def test_360_pd_is_causal_not_forced_back_inside_htf_zone():
    text = _text()
    pd = text[text.index("bool TZ60_FindAnyCausalPD"):text.index("bool TZ60_RecentZoneContext")]
    assert "Intersect(" not in pd
    assert "g_plan.zone_low" not in pd
    assert "g_plan.zone_high" not in pd
    assert 'pdType="FVG"' in pd
    assert 'pdType="OB"' in pd


def test_360_order_block_uses_rejection_wick_geometry():
    text = _text()
    pd = text[text.index("bool TZ60_FindAnyCausalPD"):text.index("bool TZ60_RecentZoneContext")]
    assert "if(buy){pdLo=r[i].low;pdHi=r[i].open;}" in pd
    assert "else {pdLo=r[i].open;pdHi=r[i].high;}" in pd


def test_360_pullback_and_confirmation_are_bounded_windows_not_exact_r2():
    text = _text()
    assert "input int SniperPullbackMaxBars=12;" in text
    assert "input int SniperConfirmMaxBars=3;" in text
    pd = text[text.index("bool TZ60_FindRetestedCausalPD"):text.index("bool TZ60_RecentZoneContext")]
    assert "1+confirmWindow" in pd
    assert "for(int pb=1;pb<=oldest;pb++)" in pd
    scan = text[text.index("bool TZ60_ScanPrimaryEngine"):text.index("\nvoid TZ_ShallowValue", text.index("bool TZ60_ScanPrimaryEngine"))]
    assert "TZ60_DirectionalClose(r[1],buy)" in scan
    assert "structureHeld" not in scan


def test_360_engulfing_is_parallel_and_recent_zone_bound():
    text = _text()
    assert "input int SniperEngulfContextBars=6;" in text
    assert "TZ60_RecentZoneContext(r,SniperEngulfContextBars)" in text
    scan = text[text.index("bool TZ60_ScanPrimaryEngine"):text.index("\nvoid TZ_ShallowValue", text.index("bool TZ60_ScanPrimaryEngine"))]
    assert scan.index("TZ60_BuildEngulfing") < scan.index("for(int sw=4;sw<=maxSweep;sw++)")


def test_360_reentries_use_same_engine_but_wait_for_protected_position():
    evaluate = _evaluate(_text())
    assert "REENTRY_WAIT_POSITION_UNPROTECTED" in evaluate
    assert "TZ60_ScanPrimaryEngine(r,origBuy,true,recentZone" in evaluate
    assert 'tag="R"+IntegerToString(g_reentries+1)' in evaluate


def test_360_preserves_hard_risk_and_safety_guards():
    text = _text()
    evaluate = _evaluate(text)
    for needle in (
        "TZ_ResearchGuards()",
        "TZ_TargetDirectionValid",
        "TZ46_InitialZoneProtectedStop",
        "TZ36_MinRRValid",
        "TZ42_RevalidateParityBeforeOrder",
        "TZ37_LotsForRisk",
    ):
        assert needle in evaluate or needle in text


def test_360_pattern_identity_uses_confirmation_bar_not_entry_tag():
    evaluate = _evaluate(_text())
    assert 'g_tzCandidateModel+"|"+IntegerToString((int)patternBreakTs)' in evaluate
    assert '"+sig.pd_type+"|"+IntegerToString((int)cb)' in evaluate


def test_databridge_158_is_not_modified_by_entry_engine_rewrite():
    bridge = _text(BRIDGE)
    assert '#property version "1.58"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.58"' in bridge
    assert "TZ60_ScanPrimaryEngine" not in bridge


def test_360_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
