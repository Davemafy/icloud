from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_48_ProfessionalConfirmationTruth.mq5"


def _text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_v148_tracks_sequence_339_and_universal_confirmation_stages():
    text = _text()
    assert '#property version "1.48"' in text
    assert '#define TZ_BRIDGE_VERSION "1.48"' in text
    assert '#define TZ_SEQUENCE_EXPECTED "3.39"' in text
    assert "TZ_SendHeartbeatV148" in text
    for stage in [
        'stage=="ENTRY_CONFIRMATION"',
        'stage=="REENTRY_CONFIRMATION"',
        'stage=="HANDOFF_CONFIRMATION"',
        'stage=="FLIP_CONFIRMATION"',
    ]:
        assert stage in text
    assert text.count('"WAITING FOR CLOSED M1 VALUE REACTION"') >= 4
