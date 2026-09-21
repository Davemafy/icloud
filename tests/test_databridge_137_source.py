from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_37_RuntimeJournalTruth.mq5"
CORE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5"


def test_v137_reports_current_bridge_and_sequence_runtime_truth():
    bridge = BRIDGE.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")

    assert '#property version "1.37"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.37"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.33"' in bridge
    assert '#define TZ_JOURNAL_BRIDGE_VERSION "1.37"' in bridge

    assert 'JournalSequenceVersion()' in core
    assert 'RuntimeStateValue("sequence_state.txt","version")' in core
    assert r'\"bridge_version\":\"%s\"' in core
    assert "TZ_JOURNAL_BRIDGE_VERSION" in core
    assert "JsonEscape(JournalSequenceVersion())" in core


def test_v137_classifies_all_current_sequence_entry_tags():
    core = CORE.read_text(encoding="utf-8")

    expected = {
        "P0": "PRIMARY",
        "R1": "REENTRY_1",
        "R2": "REENTRY_2",
        "F0": "ZONE_FLIP",
        "FR1": "FLIP_REENTRY_1",
        "FR2": "FLIP_REENTRY_2",
        "S0": "ZONE_SWEEP_CONTINUATION",
        "L0": "LIQUIDITY_REVERSAL",
        "C0": "CONTINUATION_RESCUE",
        "E0": "ESCAPE_PULLBACK",
    }
    for tag, setup in expected.items():
        assert f'if(tag=="{tag}")return "{setup}";' in core
