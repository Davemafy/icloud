from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_57_StrategicEntryTruth.mq5"
CORE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_33_StrategicEntryJournal.mq5"


def test_bridge_157_tracks_sequence_347_and_new_journal_core():
    text = BRIDGE.read_text(encoding="utf-8")
    for needle in (
        '#property version "1.57"',
        '#define TZ_JOURNAL_BRIDGE_VERSION "1.33"',
        '#define TZ_BRIDGE_VERSION "1.57"',
        '#define TZ_SEQUENCE_EXPECTED "3.47"',
        'InstitutionalSMC_DataBridge_v1_33_StrategicEntryJournal.mq5',
    ):
        assert needle in text, needle


def test_journal_core_133_recovers_strategic_setup_tags():
    text = CORE.read_text(encoding="utf-8")
    expected = {
        "MP0": "MOMENTUM_PULLBACK",
        "VW0": "VWAP_PROXY_RECLAIM",
        "OR0": "OPENING_RANGE_RETEST",
        "MR1": "MOMENTUM_REENTRY_1",
        "MR2": "MOMENTUM_REENTRY_2",
        "VR1": "VWAP_RECLAIM_REENTRY_1",
        "VR2": "VWAP_RECLAIM_REENTRY_2",
        "ORR1": "OPENING_RANGE_REENTRY_1",
        "ORR2": "OPENING_RANGE_REENTRY_2",
    }
    assert '#property version "1.33"' in text
    for tag, setup in expected.items():
        assert f'if(tag=="{tag}")return "{setup}";' in text


def test_bridge_157_sources_are_structurally_balanced():
    for path in (BRIDGE, CORE):
        text = path.read_text(encoding="utf-8")
        for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
            assert text.count(left) == text.count(right), (path.name, left, right)
