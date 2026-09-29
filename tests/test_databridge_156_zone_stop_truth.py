from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_56_ZoneStopTruth.mq5"


def test_bridge_156_tracks_sequence_346_truth():
    text = BRIDGE.read_text(encoding="utf-8")
    for needle in (
        '#property version "1.56"',
        '#define TZ_BRIDGE_VERSION "1.56"',
        '#define TZ_SEQUENCE_EXPECTED "3.46"',
        '#define TZ_ZONE_RENDER_CONTRACT "V662"',
        'if(!g_tzrZones[i].valid || g_tzrZones[i].role!="PRIMARY")continue;',
        'SMC Cloud | HTF MAP ',
    ):
        assert needle in text, needle


def test_bridge_156_source_is_structurally_balanced():
    text = BRIDGE.read_text(encoding="utf-8")
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
