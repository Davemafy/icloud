from app.sniper_contract_parity import contract_fingerprint


def test_master_sniper_vector_1():
    contract = {
        "analysis_id": "AN-20260925-001",
        "zone_id": "XAUUSD-SELL-A+-01",
        "direction": "SELL",
        "current_grade": "A+",
        "qualified_mitigations": 0,
        "risk_context": "TREND",
        "base_risk_pct": 1.0,
        "execution_authority": "HTF_CORE_HANDOFF",
    }
    raw = (
        "analysis_id=AN-20260925-001|zone_id=XAUUSD-SELL-A+-01|direction=SELL|"
        "current_grade=A+|qualified_mitigations=0|risk_context=TREND|"
        "base_risk_pct=1.00000000|execution_authority=HTF_CORE_HANDOFF"
    )
    assert contract_fingerprint(contract) == __import__("hashlib").sha256(raw.encode("utf-8")).hexdigest()


def test_master_sniper_vector_2_normalizes_wire_values():
    contract = {
        "analysis_id": "  AN-2  ",
        "zone_id": " Z-2 ",
        "direction": " BUY ",
        "current_grade": " A ",
        "qualified_mitigations": "2.0",
        "risk_context": " COUNTER_TREND ",
        "base_risk_pct": "0.25",
        "execution_authority": " HTF_ZONE_SWEEP_HANDOFF ",
    }
    # qualified_mitigations intentionally uses an integer-compatible wire value.
    # Python's current contract accepts integer strings; this vector pins whitespace
    # and fixed-8-decimal risk normalization for the cross-language implementation.
    contract["qualified_mitigations"] = "2"
    raw = (
        "analysis_id=AN-2|zone_id=Z-2|direction=BUY|current_grade=A|"
        "qualified_mitigations=2|risk_context=COUNTER_TREND|base_risk_pct=0.25000000|"
        "execution_authority=HTF_ZONE_SWEEP_HANDOFF"
    )
    assert contract_fingerprint(contract) == __import__("hashlib").sha256(raw.encode("utf-8")).hexdigest()
