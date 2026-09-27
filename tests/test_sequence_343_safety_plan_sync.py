from pathlib import Path

SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_45_OwnerLifecyclePriority_Demo.mq5")


def test_live_block_does_not_erase_plan_authority_or_parity():
    text = SEQ.read_text(encoding="utf-8")
    refresh = text[text.index("bool TZ31_RefreshCloudState"):text.index("void TZ_WriteSequenceState")]
    assert 'Plan p;if(!ParsePlanText(text,p))' in refresh
    assert 'g_tzExecutionAuthority=KV(text,"execution_authority")' in refresh
    assert 'TZ42_RefreshSniperParityFromPlan(text);' in refresh
    assert 'g_tzCloudLiveBlocked=(KV(text,"live_block")=="1");' in refresh
    assert 'g_plan.valid=false;g_tzExecutionAuthority="NONE"' not in refresh
    assert refresh.index('TZ42_RefreshSniperParityFromPlan(text);') < refresh.index('g_tzCloudLiveBlocked=(KV(text,"live_block")=="1");')


def test_cloud_live_block_is_enforced_in_order_guards():
    text = SEQ.read_text(encoding="utf-8")
    guards = text[text.index("bool TZ_ResearchGuards"):text.index("bool TZ_TargetDirectionValid")]
    assert 'if(g_tzCloudLiveBlocked)' in guards
    assert 'CLOUD_LIVE_BLOCK:' in guards
    assert 'if(!TZ42_NewEntryParitySafe())return false;' in guards


def test_sequence_version_is_345():
    text = SEQ.read_text(encoding="utf-8")
    assert '#property version   "3.45"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.45"' in text
