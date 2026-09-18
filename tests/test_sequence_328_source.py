from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_28_AcceptedFlipHandoff_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v328_declares_dedicated_accepted_flip_handoff():
    text = _text()
    assert '#property version   "3.28"' in text
    assert 'ACCEPTED_ZONE_FLIP_HANDOFF' in text
    assert 'M15 accepted invalidation is detected before cloud authority can disappear.' in text
    assert 'invalidat' in text.lower() and 'never an entry' in text.lower()


def test_invalidation_is_armed_before_cloud_authority_guard():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    arm = evaluate.index("TZ28_ArmAcceptedFlip();")
    refresh = evaluate.index("RefreshPlan();")
    research_guard = evaluate.index("TZ_ResearchGuards()")
    assert arm < refresh < research_guard


def test_flip_candidate_persists_failed_zone_geometry():
    text = _text()
    for needle in (
        'accepted_flip_state.txt',
        'g_tzFlipPlan=g_plan',
        'g_tzFlipAcceptedAt',
        'TZ28_LoadAcceptedFlip',
        'TZ28_SaveAcceptedFlip',
    ):
        assert needle in text


def test_flip_authority_is_only_set_after_buildflip_signal():
    text = _text()
    fn = text[text.index("void TZ28_EvaluateAcceptedFlip()"):text.index("\nvoid TZ_JsonEscape", text.index("void TZ28_EvaluateAcceptedFlip()")) if "\nvoid TZ_JsonEscape" in text[text.index("void TZ28_EvaluateAcceptedFlip()"):] else text.index("\nstring TZ_JsonEscape", text.index("void TZ28_EvaluateAcceptedFlip()"))]
    signal_pos = fn.index("if(BuildFlip")
    authority_pos = fn.index('g_tzExecutionAuthority="ACCEPTED_ZONE_FLIP_HANDOFF"')
    assert signal_pos < authority_pos
    assert 'g_tzExecutionAuthority="NONE";' in fn[:signal_pos]


def test_flip_still_requires_retest_value_target_and_safety():
    text = _text()
    for needle in (
        "BuildFlip(r,a,flipBuy,sig)",
        "EntryAtValue(sig.buy,entry,sig,a)",
        "TZ_TargetDirectionValid(true,sig.buy,entry)",
        "TZ28_FlipSafetyGuards",
        "SPREAD_TOO_HIGH",
        "FLIP_CLOUD_LIVE_BLOCK",
        "MT5_FLIP_ORDER_SEND_FAILED",
    ):
        assert needle in text
