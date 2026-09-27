from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_45_OwnerLifecyclePriority_Demo.mq5")


def test_active_owner_priority_is_decided_before_flip_can_mutate_authority():
    text = SEQ.read_text(encoding="utf-8")
    assert "bool TZ45_ActiveOwnerMatchesCurrentPlan()" in text
    helper = text[
        text.index("bool TZ45_ActiveOwnerMatchesCurrentPlan()"):
        text.index("\nvoid Evaluate()", text.index("bool TZ45_ActiveOwnerMatchesCurrentPlan()"))
    ]
    for needle in (
        'TZ30_OwnerKV("owner_mirror_active")!="1"',
        'ownerId!=g_plan.zone_id',
        'ownerDir!=g_plan.original_direction',
        'ownerStatus!="INTERACTING"',
        'ownerStatus!="REACTION_CONFIRMED"',
        'ownerStatus!="OBJECTIVE_IN_PROGRESS"',
        'ownerAuthority!="HTF_CORE_HANDOFF"',
        'ownerAuthority!="HTF_ZONE_SWEEP_HANDOFF"',
        'ownerAuthority!="LIQUIDITY_REVERSAL_HANDOFF"',
    ):
        assert needle in helper

    # Critical regression: owner priority cannot depend on the mutable authority
    # variable because accepted-flip arming/evaluation is allowed to set it NONE.
    assert "g_tzExecutionAuthority!=ownerAuthority" not in helper

    evaluate = text[
        text.index("void Evaluate()"):
        text.index("\nint OnInit()", text.index("void Evaluate()"))
    ]
    assert "if(!TZ45_ActiveOwnerMatchesCurrentPlan())TZ28_ArmAcceptedFlip();" in evaluate
    refresh = evaluate.index("TZ31_RefreshCloudState(false)")
    owner_after_refresh = evaluate.index("bool ownerPriority=TZ45_ActiveOwnerMatchesCurrentPlan();")
    flip_eval = evaluate.index("TZ28_EvaluateAcceptedFlip()")
    assert refresh < owner_after_refresh < flip_eval
    assert "if(!ownerPriority)" in evaluate


def test_tick_timer_and_boot_do_not_arm_flip_over_matching_live_owner():
    text = SEQ.read_text(encoding="utf-8")
    assert text.count("if(!TZ45_ActiveOwnerMatchesCurrentPlan())TZ28_ArmAcceptedFlip();") >= 4
    on_tick = text[text.index("void OnTick()"):]
    assert "if(!TZ45_ActiveOwnerMatchesCurrentPlan())TZ28_ArmAcceptedFlip();" in on_tick
    on_timer = text[text.index("void OnTimer()"):text.index("void OnTick()")]
    assert "if(!TZ45_ActiveOwnerMatchesCurrentPlan())TZ28_ArmAcceptedFlip();" in on_timer


def test_owner_priority_does_not_weaken_cloud_or_local_safety_guards():
    text = SEQ.read_text(encoding="utf-8")
    guards = text[text.index("bool TZ_ResearchGuards"):text.index("bool TZ_TargetDirectionValid")]
    assert "if(g_tzCloudLiveBlocked)" in guards
    assert 'TZ_SetGate("SAFETY","CLOUD_LIVE_BLOCK:"+g_tzCloudLiveBlockReason)' in guards
    assert "SPREAD_TOO_HIGH" in text
    assert "if(!TZ42_NewEntryParitySafe())return false;" in guards
    assert 'if(g_plan.ea_mode!="DUAL_BRANCH")' in guards
    assert '#property version   "3.45"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.45"' in text
