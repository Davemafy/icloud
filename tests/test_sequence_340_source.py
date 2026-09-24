from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "mt5" / "stable" / "InstitutionalSMC_SequenceEA_v3_41_BPlusAuthority_Demo.mq5"


def _text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_v340_adds_failed_zone_breaker_flip_without_instant_reverse():
    text = _text()
    assert '#property version   "3.41"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.41"' in text
    assert "#define BuildFlip TZ21_BaseBuildFlip" in text
    assert "#undef BuildFlip" in text
    assert "TZ40_FailedZoneBreakerPD" in text
    assert "BREAKER-CORE" in text
    assert "BREAKER-PROXIMAL" in text
    assert "TZ40_BreakerFlipReady" in text
    assert "BREAKER_RETEST_MSS_DISPLACEMENT_CONFIRMED" in text
    assert "BREAKER_CONFIRMED_BUT_CHASED" in text
    assert "ACCEPTED_ZONE_FLIP_HANDOFF" in text
    assert "M15_ACCEPTED_INVALIDATION_WAIT_OPPOSITE_RETEST" in text


def test_v340_breaker_flip_still_requires_retest_structure_displacement_and_no_chase():
    text = _text()
    start = text.index("bool BuildFlip(")
    end = text.index("string TZ38_DefaultRiskContext", start)
    block = text[start:end]
    for needle in [
        "if(r[i].time<g_flipAcceptedAt)continue;",
        "if(!TouchZone(r[i]))continue;",
        "OlderPivot(r,ret+2,SwingLookback,buy,bp,bos)",
        "StrongDisp(r,j,a,FlipBreakDisplacementATR,buy)",
        "OTE(buy,anchor,imp,ol,oh)",
        "FindFreshPD",
        "TZ40_FailedZoneBreakerPD",
    ]:
        assert needle in block

    ready_start = text.index("bool TZ40_BreakerFlipReady")
    ready_end = text.index("void TZ36_SendEntryDecisionAudit", ready_start)
    ready = text[ready_start:ready_end]
    for needle in [
        "retestTouched",
        "directional",
        "rejected",
        "microBreak",
        "ProfessionalEntryReactionMinBodyATR",
        "ProfessionalEntryReactionMaxChaseATR",
        "CONFIRMED_BUT_CHASED",
    ]:
        assert needle in ready


def test_v340_preserves_v339_professional_confirmation_for_non_breaker_entries():
    text = _text()
    for needle in [
        "TZ39_ProfessionalValueReactionReady",
        "TZ39_InitialEntryReady",
        "TZ35_ReentryEntryReady",
        "TZ36_PostHandoffEntryReady",
        "TZ39_FlipEntryReady",
        "ProfessionalEntryReactionMinBodyATR=0.25",
        "ProfessionalEntryReactionMaxChaseATR=0.15",
        "TZ_TargetDirectionValid",
        "TZ36_MinRRValid",
        "TZ37_LotsForRisk",
    ]:
        assert needle in text
