from app.live_ownership_sync import _append_guard_reason
from app.sniper_contract_parity import (
    contract_fingerprint,
    evaluate_sequence_parity,
    finalize_plan_contract_text,
    plan_contract_from_kv,
    plan_contract_from_text,
    sequence_contract_from_details,
)


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


def _sequence(**overrides):
    out = dict(_cloud())
    out.update(overrides)
    out["contract_fingerprint"] = contract_fingerprint(out)
    return out


def test_legacy_sequence_is_unverified_not_matched():
    out = evaluate_sequence_parity(_cloud(), {"analysis_id": "A1", "zone_id": "Z1"}, online=True)
    assert out["status"] == "UNVERIFIED"
    assert out["reason"] == "LEGACY_TELEMETRY"
    assert out["new_entry_safe"] is False


def test_complete_fields_without_fingerprint_are_unverified():
    out = evaluate_sequence_parity(_cloud(), _cloud(), online=True)
    assert out["status"] == "UNVERIFIED"
    assert out["reason"] == "INCOMPLETE_PARITY_TELEMETRY"
    assert out["missing_fields"] == ["contract_fingerprint"]
    assert out["new_entry_safe"] is False


def test_complete_matching_contract_is_verified():
    seq = _sequence()
    out = evaluate_sequence_parity(_cloud(), seq, online=True)
    assert out["status"] == "MATCH"
    assert out["verified"] is True
    assert out["new_entry_safe"] is True
    assert out["cloud_fingerprint"] == out["computed_sequence_fingerprint"]
    assert out["sequence_fingerprint"] == out["cloud_fingerprint"]


def test_fingerprint_is_stable_across_numeric_wire_representations():
    a = _cloud()
    b = _cloud()
    b["qualified_mitigations"] = "1"
    b["base_risk_pct"] = "1.00000000"
    assert contract_fingerprint(a) == contract_fingerprint(b)


def test_fingerprint_changes_for_every_authoritative_field():
    baseline = contract_fingerprint(_cloud())
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
        changed = _cloud()
        changed[field] = value
        assert contract_fingerprint(changed) != baseline


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
        seq = _sequence(**{field: value})
        out = evaluate_sequence_parity(_cloud(), seq, online=True)
        assert out["status"] == "MISMATCH"
        assert out["reason"] == "SNIPER_CONTRACT_MISMATCH"
        assert field in out["mismatches"]
        assert out["new_entry_safe"] is False


def test_wrong_wire_fingerprint_is_a_mismatch_even_when_fields_match():
    seq = _sequence()
    seq["contract_fingerprint"] = "0" * 64
    out = evaluate_sequence_parity(_cloud(), seq, online=True)
    assert out["status"] == "MISMATCH"
    assert "contract_fingerprint" in out["mismatches"]
    assert out["new_entry_safe"] is False


def test_mismatch_does_not_revoke_open_position_management():
    seq = _sequence(zone_id="STALE")
    out = evaluate_sequence_parity(_cloud(), seq, online=True, open_positions=1)
    assert out["new_entry_safe"] is False
    assert out["position_management_safe"] is True


def test_offline_sequence_is_not_entry_safe():
    out = evaluate_sequence_parity(_cloud(), {}, online=False)
    assert out["status"] == "OFFLINE"
    assert out["new_entry_safe"] is False


def test_final_plan_kv_uses_explicit_current_grade_mitigations_and_authority():
    kv = {
        "analysis_id": "A1",
        "zone_id": "Z1",
        "original_direction": "SELL",
        "grade": "A+",
        "current_grade": "A",
        "touch_count": "9",
        "qualified_mitigations": "1",
        "risk_context": "TREND",
        "original_risk_pct": "0.75",
        "execution_authority": "HTF_CORE_HANDOFF",
    }
    out = plan_contract_from_kv(kv)
    assert out["direction"] == "SELL"
    assert out["current_grade"] == "A"
    assert out["qualified_mitigations"] == "1"
    assert out["base_risk_pct"] == "0.75"
    assert out["execution_authority"] == "HTF_CORE_HANDOFF"


def test_sequence_contract_prefers_loaded_contract_authority_over_runtime_gate_authority():
    details = {
        **_cloud(),
        "execution_authority": "ACCEPTED_ZONE_FLIP_HANDOFF",
        "contract_execution_authority": "PRIMARY",
    }
    details["contract_fingerprint"] = contract_fingerprint(_cloud())
    out = sequence_contract_from_details(details)
    assert out["execution_authority"] == "PRIMARY"
    assert out["contract_fingerprint"] == contract_fingerprint(_cloud())


def test_finalizer_recomputes_fingerprint_after_authority_changes():
    raw = (
        "analysis_id=A1\n"
        "zone_id=Z1\n"
        "original_direction=SELL\n"
        "grade=A+\n"
        "current_grade=A+\n"
        "qualified_mitigations=1\n"
        "risk_context=TREND\n"
        "original_risk_pct=1.00\n"
        "execution_authority=NONE\n"
        "contract_fingerprint=stale\n"
    )
    final = finalize_plan_contract_text(raw)
    contract = plan_contract_from_text(final)
    lines = dict(line.split("=", 1) for line in final.splitlines() if "=" in line)
    assert lines["base_risk_pct"] == "1.00000000"
    assert lines["sniper_parity_version"] == "SNIPER_PARITY_V1"
    assert lines["contract_fingerprint"] == contract_fingerprint(contract)
    assert lines["contract_fingerprint"] != "stale"


def test_live_ownership_fail_closed_mutation_is_refingerprinted():
    raw = (
        "analysis_id=A1\n"
        "zone_id=Z1\n"
        "original_direction=SELL\n"
        "grade=A+\n"
        "current_grade=A+\n"
        "qualified_mitigations=1\n"
        "risk_context=TREND\n"
        "original_risk_pct=1.00\n"
        "execution_authority=HTF_CORE_HANDOFF\n"
        "ea_mode=DUAL_BRANCH\n"
    )
    before = finalize_plan_contract_text(raw)
    before_lines = dict(line.split("=", 1) for line in before.splitlines() if "=" in line)
    blocked = _append_guard_reason(before, "LIVE_THESIS_OWNER_SELECTION_MISMATCH")
    blocked_lines = dict(line.split("=", 1) for line in blocked.splitlines() if "=" in line)
    assert blocked_lines["execution_authority"] == "NONE"
    assert blocked_lines["contract_fingerprint"] == before_lines["contract_fingerprint"]

    final = finalize_plan_contract_text(blocked)
    final_lines = dict(line.split("=", 1) for line in final.splitlines() if "=" in line)
    contract = plan_contract_from_text(final)
    assert final_lines["execution_authority"] == "NONE"
    assert final_lines["contract_fingerprint"] == contract_fingerprint(contract)
    assert final_lines["contract_fingerprint"] != before_lines["contract_fingerprint"]


def test_package_installs_sniper_finalizer_after_live_ownership_wrapper():
    text = __import__("pathlib").Path("app/__init__.py").read_text(encoding="utf-8")
    assert text.index("install_live_ownership_sync()") < text.index("install_plan_contract_finalizer()")
