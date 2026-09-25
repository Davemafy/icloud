from pathlib import Path
import subprocess
import sys


MQL = Path("mt5/include/SniperContractParityV1.mqh")
SEQ342 = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_42_SniperContractParity_Demo.mq5")
BRIDGE151 = Path("mt5/stable/InstitutionalSMC_DataBridge_v1_51_SniperContractParity.mq5")
STABLE_INCLUDE = Path("mt5/stable/SniperContractParityV1.mqh")


def test_mql_parity_module_has_canonical_contract_and_sha256():
    text = MQL.read_text(encoding="utf-8")
    required = [
        'TZ_SNIPER_PARITY_VERSION "SNIPER_PARITY_V1"',
        "string TZ_SniperCanonicalContract(",
        '"analysis_id="+TZ_SniperTrim(analysis_id)',
        '"|zone_id="+TZ_SniperTrim(zone_id)',
        '"|direction="+TZ_SniperTrim(direction)',
        '"|current_grade="+TZ_SniperTrim(current_grade)',
        '"|qualified_mitigations="+IntegerToString(qualified_mitigations)',
        '"|risk_context="+TZ_SniperTrim(risk_context)',
        '"|base_risk_pct="+TZ_SniperCanonicalRisk(base_risk_pct)',
        '"|execution_authority="+TZ_SniperTrim(execution_authority)',
        "return DoubleToString(value,8);",
        "int n=StringToCharArray(text,msg,0,-1,CP_UTF8);",
        "if(n>0 && msg[n-1]==0) n--;",
        "string TZ_SniperSHA256(const string text)",
        "string TZ_SniperContractFingerprint(",
    ]
    for needle in required:
        assert needle in text, needle


def test_mql_sha256_constants_are_complete_and_unique_enough():
    text = MQL.read_text(encoding="utf-8")
    for needle in (
        "0x6a09e667",
        "0xbb67ae85",
        "0x3c6ef372",
        "0xa54ff53a",
        "0x510e527f",
        "0x9b05688c",
        "0x1f83d9ab",
        "0x5be0cd19",
        "0x428a2f98",
        "0xc67178f2",
    ):
        assert needle in text
    assert "uint k[64]" in text
    assert 'StringFormat("%08x%08x%08x%08x%08x%08x%08x%08x"' in text


def test_native_proof_unlocked_immutable_342_151_candidates():
    seq = SEQ342.read_text(encoding="utf-8")
    bridge = BRIDGE151.read_text(encoding="utf-8")
    assert STABLE_INCLUDE.read_text(encoding="utf-8") == MQL.read_text(encoding="utf-8")
    assert '#property version   "3.42"' in seq
    assert '#define TZ_SEQUENCE_VERSION "3.42"' in seq
    assert '#include <TradeZoneCore\\SniperContractParityV1.mqh>' in seq
    assert "TZ42_RefreshSniperParityFromPlan" in seq
    for needle in (
        r'\"direction\":\"%s\"',
        r'\"current_grade\":\"%s\"',
        r'\"qualified_mitigations\":%d',
        r'\"risk_context\":\"%s\"',
        r'\"base_risk_pct\":%s',
        r'\"contract_fingerprint\":\"%s\"',
        r'\"expected_contract_fingerprint\":\"%s\"',
        r'\"contract_execution_authority\":\"%s\"',
        r'\"contract_parity_status\":\"%s\"',
        "TZ42_NewEntryParitySafe",
        'TZ_SetGate("PARITY","SNIPER_CONTRACT_UNVERIFIED")',
        'TZ_SetGate("PARITY","SNIPER_CONTRACT_MISMATCH")',
        "g_tzFlipSniperContractVerified",
        "sniper_contract_verified=",
        "sniper_contract_fingerprint=",
    ):
        assert needle in seq
    assert "TZ_PreCoreSync();ManagePositions();Evaluate();" in seq
    assert 'if(!TZ42_NewEntryParitySafe())return false;' in seq
    assert '#property version "1.51"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.51"' in bridge
    assert '#define TZ_SEQUENCE_EXPECTED "3.42"' in bridge


def test_release_candidate_verifier_is_fail_closed_and_manifest_remains_locked():
    text = Path("scripts/sniper_contract_parity_release.py").read_text(encoding="utf-8")
    assert "verify_immutable_sources()" in text
    assert "verify_sequence_candidate()" in text
    assert "verify_bridge_candidate()" in text
    assert "verify_parity_include()" in text
    assert "verify_manifest_still_locked()" in text
    assert "6.3.31" in text and "1.50" in text and "3.41" in text


def test_release_candidate_verifier_executes_cleanly():
    proc = subprocess.run(
        [sys.executable, "scripts/sniper_contract_parity_release.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "Master Sniper parity candidates verified." in proc.stdout
    assert "Stable manifest remains locked at 6.3.31 / 1.50 / 3.41." in proc.stdout
