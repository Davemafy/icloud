from app.sniper_contract_parity import contract_fingerprint


VECTORS = [
    (
        {
            "analysis_id": "A-001",
            "zone_id": "Z-SELL-1",
            "direction": "SELL",
            "current_grade": "A+",
            "qualified_mitigations": 0,
            "risk_context": "TREND",
            "base_risk_pct": 1.0,
            "execution_authority": "HTF_CORE_HANDOFF",
        },
        "analysis_id=A-001|zone_id=Z-SELL-1|direction=SELL|current_grade=A+|qualified_mitigations=0|risk_context=TREND|base_risk_pct=1.00000000|execution_authority=HTF_CORE_HANDOFF",
        "5d0c3fc29439bdcacb13c413f485b83e8af1cfe66f762c8cd43fb6ee4af6886e",
    ),
    (
        {
            "analysis_id": "  A-002  ",
            "zone_id": "Z2",
            "direction": "BUY",
            "current_grade": "A",
            "qualified_mitigations": "2",
            "risk_context": "COUNTERTREND",
            "base_risk_pct": "0.25",
            "execution_authority": "NONE",
        },
        "analysis_id=A-002|zone_id=Z2|direction=BUY|current_grade=A|qualified_mitigations=2|risk_context=COUNTERTREND|base_risk_pct=0.25000000|execution_authority=NONE",
        "7f9196603934fb931dc7ad57db12d64552e0c1086959b3ea7603c8d452dbc5c7",
    ),
]


def _canonical_raw(contract):
    fields = (
        "analysis_id",
        "zone_id",
        "direction",
        "current_grade",
        "qualified_mitigations",
        "risk_context",
        "base_risk_pct",
        "execution_authority",
    )
    values = []
    for field in fields:
        value = contract.get(field)
        if field == "base_risk_pct":
            value = f"{float(value or 0.0):.8f}"
        elif field == "qualified_mitigations":
            value = str(int(value or 0))
        else:
            value = str(value or "").strip()
        values.append(f"{field}={value}")
    return "|".join(values)


def test_cross_language_fingerprint_vectors_are_frozen():
    for contract, canonical, digest in VECTORS:
        assert _canonical_raw(contract) == canonical
        assert contract_fingerprint(contract) == digest
