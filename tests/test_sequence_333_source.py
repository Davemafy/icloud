from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_33_SafetyPersistentOwner_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v333_persists_owner_mirror_before_live_safety_block():
    text = _text()
    assert '#property version   "3.33"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.33"' in text
    start = text.index("bool TZ31_RefreshCloudState")
    end = text.index("\nvoid TZ_WriteSequenceState()", start)
    fn = text[start:end]
    mirror = fn.index("TZ30_SaveOwnerMirrorFromPlan(text);")
    block = fn.index('if(KV(text,"live_block")=="1")')
    assert mirror < block
    assert 'TZ_SetGate("SAFETY","CLOUD_LIVE_BLOCK:"' in fn


def test_v333_keeps_release_safe_mirror_and_execution_guards():
    text = _text()
    assert 'FileDelete("TradeZone\\\\execution_owner_state.txt")' in text
    for needle in (
        "HTF_ZONE_SWEEP_HANDOFF",
        "LIQUIDITY_REVERSAL_HANDOFF",
        "ACCEPTED_ZONE_FLIP_HANDOFF",
        "TZ31_BuildPostHandoffContinuation",
        "EntryAtValue(sig.buy,entry,sig,a)",
        "TZ_TargetDirectionValid(false,sig.buy,entry)",
        "LotsForRisk(entry,sl,risk)",
        "SIGNAL_FOUND_WAITING_FOR_PULLBACK",
        "MT5_ORDER_SEND_FAILED",
    ):
        assert needle in text
