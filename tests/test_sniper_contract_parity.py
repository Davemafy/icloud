from app.sniper_contract_parity import evaluate_sequence_parity


def _cloud():
    return {
        "analysis_id": "A1",
        "zone_id": "Z1",
        "direction": "SELL",
        "current_grade": "A+",
        "qualified_mitigations": 1,
        "risk_context": "TREND",
        "base_risk_pct": 1.0,
        "execution_authority": "PRIMARY",
    }


def test_legacy_sequence_is_unverified_not_matched():
    out = evaluate_sequence_parity(_cloud(), {"analysis_id": "A1", "zone_id": "Z1"}, online=True)
    assert out["status"] == "UNVERIFIED"
    assert out["reason"] == "LEGACY_TELEMETRY"
    assert out["new_entry_safe"] is False


def test_complete_matching_contract_is_verified():
    out = evaluate_sequence_parity(_cloud(), _cloud(), online=True)
    assert out["status"] == "MATCH"
    assert out["verified"] is True
    assert out["new_entry_safe"] is True


def test_any_contract_difference_fails_closed_for_new_entries():
    for field, value in {
        "analysis_id": "A2",
        "zone_id": "Z2",
        "direction": "BUY",
        "current_grade": "A",
        "qualified_mitigations": 2,
        "risk_context": "COUNTERTREND",
        "base_risk_pct": 0.5,
        "execution_authority": "NONE",
    }.items():
        seq = _cloud()
        seq[field] = value
        out = evaluate_sequence_parity(_cloud(), seq, online=True)
        assert out["status"] == "MISMATCH"
        assert out["reason"] == "SNIPER_CONTRACT_MISMATCH"
        assert field in out["mismatches"]
        assert out["new_entry_safe"] is False


def test_mismatch_does_not_revoke_open_position_management():
    seq = _cloud()
    seq["zone_id"] = "STALE"
    out = evaluate_sequence_parity(_cloud(), seq, online=True, open_positions=1)
    assert out["new_entry_safe"] is False
    assert out["position_management_safe"] is True


def test_offline_sequence_is_not_entry_safe():
    out = evaluate_sequence_parity(_cloud(), {}, online=False)
    assert out["status"] == "OFFLINE"
    assert out["new_entry_safe"] is False
