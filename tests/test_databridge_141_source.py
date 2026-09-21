from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_41_JournalProvenance.mq5"
CORE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5"


def test_v141_provenance_runtime_contract():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")

    assert '#property version "1.41"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.41"' in bridge
    assert '#define TZ_JOURNAL_BRIDGE_VERSION "1.41"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.34"' in bridge
    assert "TZ_SendHeartbeatV141();" in bridge
    assert 'TZ_SendSnapshotCycle("V141_VERIFY")' in bridge

    for needle in [
        "PositionMetaFile",
        "SavePositionMeta",
        "LoadPositionMeta",
        "execution_bridge_version",
        "execution_sequence_version",
        "execution_cloud_version",
        "recovery_bridge_version",
        "recovery_sequence_version",
        "recovery_cloud_version",
        "LIVE_ENTRY_CONTEXT",
        "LOCAL_POSITION_METADATA",
        "UNAVAILABLE_FROM_MT5_HISTORY",
        "MT5_HISTORY_RECOVERY",
    ]:
        assert needle in core


def test_v141_recovery_stays_read_only():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")
    for text in (bridge, core):
        assert "OrderSend(" not in text
        assert "trade.Buy(" not in text
        assert "trade.Sell(" not in text
