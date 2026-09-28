import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEQ = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_45_OwnerLifecyclePriority_Demo.mq5"
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_54_MapExecutionTruth.mq5"
INCLUDE = ROOT / "mt5/stable/SniperContractParityV1.mqh"
MANIFEST = ROOT / "mt5/stable/manifest.json"

EXPECTED = {
    SEQ: "c77c691c33036880a9c6a5521de18e8ae96f60b086d1395d9bca737230f371f9",
    BRIDGE: "f2e8139b769d52865703f895e53bbf51aeaebf7de51c7ddeb6d146d71883b4cc",
    INCLUDE: "5002ee0c56900ed1baee056ed4cba882f1a99627824ccf399ecdf3ac24a4eee0",
}


def test_release_payload_hashes_are_frozen():
    for path, expected in EXPECTED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_release_payload_versions_and_parity_wiring():
    seq = SEQ.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")
    inc = INCLUDE.read_text(encoding="utf-8")
    assert '#property version   "3.45"' in seq
    assert '#define TZ_SEQUENCE_VERSION "3.45"' in seq
    assert '#include <TradeZoneCore\\SniperContractParityV1.mqh>' in seq
    assert 'TZ_PreCoreSync();ManagePositions();Evaluate();' in seq
    assert seq.index("ManagePositions();") < seq.index("Evaluate();")
    assert '#property version "1.54"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.54"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.45"' in bridge
    assert 'TZ_SNIPER_PARITY_VERSION "SNIPER_PARITY_V1"' in inc


def test_release_manifest_promotes_exact_parity_payload():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["release"] == "6.3.37"
    assert manifest["ref"] == "a93820faff4e24eb14ea563adae8ed0d3c85b449"
    assert manifest["data_bridge_version"] == "1.54"
    assert manifest["sequence_ea_version"] == "3.45"
    files = {item["role"]: item for item in manifest["files"]}
    assert files["data_bridge"]["sha256"] == EXPECTED[BRIDGE]
    assert files["sequence_ea"]["sha256"] == EXPECTED[SEQ]
    supports = {item["role"]: item for item in manifest["support_files"]}
    assert supports["sniper_contract_parity"]["sha256"] == EXPECTED[INCLUDE]
    assert supports["sniper_contract_parity"]["target"] == "Include\\TradeZoneCore"
