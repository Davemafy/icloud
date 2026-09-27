import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEQ = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_44_OwnerFlipPriority_Demo.mq5"
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_52_SafetyPlanSync.mq5"
INCLUDE = ROOT / "mt5/stable/SniperContractParityV1.mqh"
MANIFEST = ROOT / "mt5/stable/manifest.json"

EXPECTED = {
    SEQ: "38e9ff572d9ac5438c28b7ed42224239f0fc46cff7eb0a402160bf0e01c14e11",
    BRIDGE: "c0e9a8ec798569998034b117e26581aefd23a497e07213665b2b5284ba4adb76",
    INCLUDE: "5002ee0c56900ed1baee056ed4cba882f1a99627824ccf399ecdf3ac24a4eee0",
}


def test_release_payload_hashes_are_frozen():
    for path, expected in EXPECTED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_release_payload_versions_and_parity_wiring():
    seq = SEQ.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")
    inc = INCLUDE.read_text(encoding="utf-8")
    assert '#property version   "3.44"' in seq
    assert '#define TZ_SEQUENCE_VERSION "3.44"' in seq
    assert '#include <TradeZoneCore\\SniperContractParityV1.mqh>' in seq
    assert 'TZ_PreCoreSync();ManagePositions();Evaluate();' in seq
    assert seq.index("ManagePositions();") < seq.index("Evaluate();")
    assert '#property version "1.52"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.52"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.43"' in bridge
    assert 'TZ_SNIPER_PARITY_VERSION "SNIPER_PARITY_V1"' in inc


def test_release_manifest_promotes_exact_parity_payload():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["release"] == "6.3.34"
    assert manifest["ref"] == "c239cda51454cad4a2f5f1820604fbd4ab5a01c5"
    assert manifest["data_bridge_version"] == "1.52"
    assert manifest["sequence_ea_version"] == "3.44"
    files = {item["role"]: item for item in manifest["files"]}
    assert files["data_bridge"]["sha256"] == EXPECTED[BRIDGE]
    assert files["sequence_ea"]["sha256"] == EXPECTED[SEQ]
    supports = {item["role"]: item for item in manifest["support_files"]}
    assert supports["sniper_contract_parity"]["sha256"] == EXPECTED[INCLUDE]
    assert supports["sniper_contract_parity"]["target"] == "Include\\TradeZoneCore"
