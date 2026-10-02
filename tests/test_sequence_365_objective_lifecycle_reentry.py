from pathlib import Path

SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_65_ObjectiveLifecycleReentry_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def test_365_version_and_owner_target_import():
    text = _text()
    assert '#property version   "3.65"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.65"' in text
    assert "g_tzOwnerMirrorMatchesPlan" in text
    assert "g_tzOwnerTarget1HitAt" in text
    assert 'KV(text,"owner_mirror_target1_hit_at")' in text
    assert 'KV(text,"owner_mirror_target2_hit_at")' in text
    assert 'KV(text,"owner_mirror_target3_hit_at")' in text


def test_365_consumed_targets_are_removed_from_reentry_ladder():
    text = _text()
    block = text[text.index("int TZ49_OpenDirectionalTargets"):text.index("bool TZ49_DeepestDirectionalTarget")]
    assert "if(!flip&&g_tzOwnerMirrorMatchesPlan)" in block
    assert "if(i==0&&g_tzOwnerTarget1HitAt>0)continue;" in block
    assert "if(i==1&&g_tzOwnerTarget2HitAt>0)continue;" in block
    assert "if((i==2||i==3)&&g_tzOwnerTarget3HitAt>0)continue;" in block


def test_365_late_stage_reentry_requires_owner_zone_reacquisition():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert "ownerCompletedTargets>=2" in evaluate
    assert "ownerMark>=g_plan.zone_low&&ownerMark<=g_plan.zone_high" in evaluate
    assert "LATE_STAGE_REENTRY_REQUIRES_OWNER_ZONE_REACQUISITION" in evaluate


def test_365_does_not_increase_reentry_cap():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert "MaxReentriesPerThesis>0&&g_reentries>=MaxReentriesPerThesis" in evaluate
    assert 'TZ_SetGate("THESIS","REENTRY_LIMIT_REACHED")' in evaluate


def test_365_keeps_364_profit_protection():
    text = _text()
    assert "ManagementTP1ClosePct=60.0" in text
    assert "TZ64_UpdateObjectiveStep" in text
    assert "NearTargetArmFraction=0.85" in text
    assert "double be=buy?(o+costBuffer):(o-costBuffer)" in text


def test_365_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
