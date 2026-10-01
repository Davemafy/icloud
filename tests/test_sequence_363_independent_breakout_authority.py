from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_63_IndependentBreakoutAuthority_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def _evaluate(text: str) -> str:
    start = text.index("void Evaluate()")
    return text[start:text.index("\nint OnInit()", start)]


def test_363_version_and_authority_contract():
    text = _text()
    assert '#property version   "3.63"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.63"' in text
    for needle in (
        "STRUCTURAL_BREAKOUT_WATCH",
        "STRUCTURAL_BREAKOUT_HANDOFF",
        "TZ63_QueueBreakoutOwnerHandoff",
        "TZ63_TryBreakoutOwnerHandoff",
        "breakout_owner_pending.txt",
        "g_tzBreakoutCampaignKey",
    ):
        assert needle in text


def test_363_breakout_watch_is_independent_of_recent_zone_contact():
    evaluate = _evaluate(_text())
    watch = evaluate[evaluate.index("else if(breakoutWatchAuthority)"):]
    watch = watch[:watch.index('else if(g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF"')]
    assert "TZ62_BuildInstitutionalBreakout" in watch
    assert "recentZone" not in watch
    assert 'tag="B0"' in watch
    assert 'g_tzCandidateModel="INSTITUTIONAL_BREAKOUT"' in watch


def test_363_breakout_uses_structural_stop_and_break_event_objective_anchor():
    evaluate = _evaluate(_text())
    assert 'bool breakoutModel=(StringFind(sig.pd_type,"BREAKOUT_")==0);' in evaluate
    assert "double sl=breakoutModel" in evaluate
    assert "?NormalizeDouble(microSl,_Digits)" in evaluate
    assert "TZ46_InitialZoneProtectedStop" in evaluate
    assert "datetime objectiveAnchor=breakoutModel?g_tzTraceSweepTs" in evaluate
    assert '"BREAKOUT_OBJECTIVE_ALREADY_TRADED"' in evaluate


def test_363_post_order_owner_handoff_is_durable_and_campaign_stable():
    text = _text()
    evaluate = _evaluate(text)
    send = evaluate.index("TZ37_SendOrders")
    handoff = evaluate.index("TZ63_QueueBreakoutOwnerHandoff")
    assert send < handoff
    assert 'planAuthority=="STRUCTURAL_BREAKOUT_WATCH"' in text
    assert '"CAMPAIGN|"+breakoutCampaign' in text
    assert "TZ63_LoadBreakoutOwnerPending()" in text
    assert text.count("TZ63_TryBreakoutOwnerHandoff(false)") >= 2


def test_363_breakout_owner_can_continue_as_r1_r2():
    evaluate = _evaluate(_text())
    authority = evaluate[evaluate.index("bool primaryAuthority="):evaluate.index("bool objectiveOpen")]
    assert 'g_tzExecutionAuthority=="STRUCTURAL_BREAKOUT_HANDOFF"' in authority
    assert "TZ62_BuildDisplacementContinuation" in evaluate
    assert 'tag="R"+IntegerToString(g_reentries+1)' in evaluate


def test_363_keeps_trade_management_unchanged_and_source_balanced():
    text = _text()
    assert "#define ManagePositions TZ21_BaseManagePositions" in text
    assert "TZ_PreCoreSync();ManagePositions();Evaluate();" in text
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
