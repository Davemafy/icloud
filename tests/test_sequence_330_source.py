from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_30_OwnerMirror_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v330_persists_cloud_owner_locally_and_reports_it_in_heartbeat():
    text = _text()
    assert '#property version   "3.30"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.30"' in text
    assert 'MT5_EXECUTION_OWNER_MIRROR_V1' in text
    assert 'execution_owner_state.txt' in text
    assert 'TZ30_SaveOwnerMirrorFromPlan(text);' in text
    assert '\"owner_mirror_contract\"' in text
    assert '\"owner_mirror_zone_id\"' in text
    assert '\"owner_mirror_status\"' in text
    assert '\"owner_mirror_target1_hit_at\"' in text


def test_v330_keeps_v329_execution_and_flip_guards():
    text = _text()
    for needle in (
        "HTF_ZONE_SWEEP_HANDOFF",
        "HTF_CORE_HANDOFF",
        "LIQUIDITY_REVERSAL_HANDOFF",
        "ACCEPTED_ZONE_FLIP_HANDOFF",
        "EntryAtValue(sig.buy,entry,sig,a)",
        "LotsForRisk(entry,sl,risk)",
        "TZ_TargetDirectionValid(false,sig.buy,entry)",
    ):
        assert needle in text
