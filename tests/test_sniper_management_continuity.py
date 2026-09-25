from pathlib import Path

from app.sniper_contract_parity import contract_fingerprint, evaluate_sequence_parity


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_42_SniperContractParity_Demo.mq5")


def _section(text: str, start: str, end: str) -> str:
    a = text.index(start)
    b = text.index(end, a + len(start))
    return text[a:b]


def test_sequence_management_runs_before_parity_gated_entry_evaluation():
    text = SEQ.read_text(encoding="utf-8")
    on_tick = _section(text, "void OnTick()", "\n}")
    assert on_tick.index("ManagePositions();") < on_tick.index("Evaluate();")

    manage = _section(text, "void ManagePositions()", "\n// Accepted-zone flip state")
    for forbidden in (
        "TZ42_NewEntryParitySafe",
        "TZ42_RevalidateParityBeforeOrder",
        "SNIPER_CONTRACT_UNVERIFIED",
        "SNIPER_CONTRACT_MISMATCH",
        "contract_fingerprint",
    ):
        assert forbidden not in manage

    evaluate = _section(text, "void Evaluate()", "\nint OnInit()")
    assert "if(!TZ42_RevalidateParityBeforeOrder())return;" in evaluate
    assert evaluate.index("TZ42_RevalidateParityBeforeOrder") < evaluate.index("TZ37_SendOrders")


def test_mismatch_blocks_new_entry_but_preserves_position_management_policy():
    cloud = {
        "analysis_id": "A1",
        "zone_id": "Z1",
        "direction": "SELL",
        "current_grade": "A+",
        "qualified_mitigations": 0,
        "risk_context": "TREND",
        "base_risk_pct": 1.0,
        "execution_authority": "HTF_CORE_HANDOFF",
    }
    sequence = dict(cloud)
    sequence["zone_id"] = "STALE-ZONE"
    sequence["contract_fingerprint"] = contract_fingerprint(sequence)

    out = evaluate_sequence_parity(cloud, sequence, online=True, open_positions=1)
    assert out["status"] == "MISMATCH"
    assert out["new_entry_safe"] is False
    assert out["position_management_safe"] is True
