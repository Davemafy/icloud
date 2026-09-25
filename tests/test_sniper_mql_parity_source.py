from pathlib import Path


MQL = Path("mt5/include/SniperContractParityV1.mqh")


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
    # Pin the standard SHA-256 IV and boundary constants so an accidental edit is caught.
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


def test_release_transformer_still_fails_closed_before_342_emit():
    text = Path("scripts/sniper_contract_parity_release.py").read_text(encoding="utf-8")
    assert "canonical MQL fingerprint parity not yet proven" in text
    assert "refusing partial 3.42 transformation" in text
