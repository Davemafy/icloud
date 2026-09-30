from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_58_EntryRunwayTruth.mq5"
CORE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_33_StrategicEntryJournal.mq5"


def test_bridge_158_tracks_sequence_348_and_preserves_journal_core():
    text = BRIDGE.read_text(encoding="utf-8")
    for needle in (
        '#property version "1.58"',
        '#define TZ_JOURNAL_BRIDGE_VERSION "1.33"',
        '#define TZ_BRIDGE_VERSION "1.58"',
        '#define TZ_SEQUENCE_EXPECTED "3.48"',
        'InstitutionalSMC_DataBridge_v1_33_StrategicEntryJournal.mq5',
    ):
        assert needle in text, needle


def test_bridge_158_sources_are_structurally_balanced():
    for path in (BRIDGE, CORE):
        text = path.read_text(encoding="utf-8")
        for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
            assert text.count(left) == text.count(right), (path.name, left, right)
