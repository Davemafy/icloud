import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEQ = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_47_StrategicMultiModel_Demo.mq5"
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_57_StrategicEntryTruth.mq5"
INCLUDE = ROOT / "mt5/stable/SniperContractParityV1.mqh"
RENDERER = ROOT / "mt5/stable/TradeZone_ZoneRenderer_v1_0.mqh"
JOURNAL_CORE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_33_StrategicEntryJournal.mq5"
MANIFEST = ROOT / "mt5/stable/manifest.json"

EXPECTED = {
    SEQ: "88415eacd960627dc4bc46cca5936211c70e3093bacebc4e7ec528268a455a02",
    BRIDGE: "a0c65c889f479ff23d1757ded80f0dd19738a4f9d8badca28d9242e82204cf05",
    INCLUDE: "5002ee0c56900ed1baee056ed4cba882f1a99627824ccf399ecdf3ac24a4eee0",
    RENDERER: "06b0b4a2d07c9acbd31a237d27826ea804c63983994e61ac003c02b7b9e92442",
    JOURNAL_CORE: "7063db3f717eca0cd6c184a5a0ee74d70e2bad78308e52cb75822d32bfdfbdd0",
}


def test_release_payload_hashes_are_frozen():
    for path, expected in EXPECTED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_release_payload_versions_and_parity_wiring():
    seq = SEQ.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")
    inc = INCLUDE.read_text(encoding="utf-8")
    assert '#property version   "3.47"' in seq
    assert '#define TZ_SEQUENCE_VERSION "3.47"' in seq
    assert '#include <TradeZoneCore\\SniperContractParityV1.mqh>' in seq
    assert 'TZ_PreCoreSync();ManagePositions();Evaluate();' in seq
    assert seq.index("ManagePositions();") < seq.index("Evaluate();")
    assert '#property version "1.57"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.57"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.47"' in bridge
    assert 'TZ_SNIPER_PARITY_VERSION "SNIPER_PARITY_V1"' in inc


def test_release_manifest_promotes_exact_parity_payload():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["release"] == "6.3.40"
    assert manifest["ref"] == "813620fe1603fe9c50173105633a800386fd6cbd"
    assert manifest["data_bridge_version"] == "1.57"
    assert manifest["sequence_ea_version"] == "3.47"
    files = {item["role"]: item for item in manifest["files"]}
    assert files["data_bridge"]["sha256"] == EXPECTED[BRIDGE]
    assert files["sequence_ea"]["sha256"] == EXPECTED[SEQ]
    supports = {item["role"]: item for item in manifest["support_files"]}
    assert supports["sniper_contract_parity"]["sha256"] == EXPECTED[INCLUDE]
    assert supports["zone_renderer"]["sha256"] == EXPECTED[RENDERER]
    assert supports["data_bridge_core"]["sha256"] == EXPECTED[JOURNAL_CORE]
    assert supports["sniper_contract_parity"]["target"] == "Include\\TradeZoneCore"
