from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_44_OwnerFlipPriority_Demo.mq5")


def test_active_owner_priority_is_checked_after_cloud_refresh_before_flip_eval():
    text = SEQ.read_text(encoding="utf-8")
    assert "bool TZ44_ActiveOwnerSupersedesStoredFlip()" in text
    helper = text[text.index("bool TZ44_ActiveOwnerSupersedesStoredFlip()"):text.index("\nvoid Evaluate()", text.index("bool TZ44_ActiveOwnerSupersedesStoredFlip()"))]
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
        "g_tzExecutionAuthority!=ownerAuthority",
    ):
        assert needle in helper

    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    refresh = evaluate.index("TZ31_RefreshCloudState(false)")
    priority = evaluate.index("TZ44_ActiveOwnerSupersedesStoredFlip()")
    flip_eval = evaluate.index("TZ28_EvaluateAcceptedFlip()")
    assert refresh < priority < flip_eval
    assert "if(!ownerSupersedesStoredFlip)" in evaluate
    assert "if(g_tzFlipPlanStored && !TZ44_ActiveOwnerSupersedesStoredFlip())" in evaluate


def test_owner_priority_does_not_weaken_cloud_or_local_safety_guards():
    text = SEQ.read_text(encoding="utf-8")
    guards = text[text.index("bool TZ_ResearchGuards"):text.index("bool TZ_TargetDirectionValid")]
    assert "if(g_tzCloudLiveBlocked)" in guards
    assert 'TZ_SetGate("SAFETY","CLOUD_LIVE_BLOCK:"+g_tzCloudLiveBlockReason)' in guards
    assert "SPREAD_TOO_HIGH" in text
    assert "if(!TZ42_NewEntryParitySafe())return false;" in guards
    assert '#property version   "3.44"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.44"' in text
