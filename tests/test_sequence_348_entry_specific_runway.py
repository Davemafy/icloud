from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_48_EntrySpecificRunway_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def test_sequence_348_enforces_actual_entry_runway_before_order():
    text = _text()
    assert '#property version   "3.48"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.48"' in text
    assert "TZ48_LoadRunwayContract" in text
    assert "TZ48_EntrySpecificRunwayValid" in text
    assert 'actualRunway=buy?(openTarget-entry):(entry-openTarget);' in text
    assert "ENTRY_SPECIFIC_RUNWAY_NOT_MET" in text

    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    target_at = evaluate.index("TZ36_NearestDirectionalTarget")
    runway_at = evaluate.index("TZ48_EntrySpecificRunwayValid")
    rr_at = evaluate.index("TZ36_MinRRValid")
    parity_at = evaluate.index("TZ42_RevalidateParityBeforeOrder")
    size_at = evaluate.index("TZ37_LotsForRisk")
    send_at = evaluate.index("TZ37_SendOrders")
    assert target_at < runway_at < rr_at < parity_at < size_at < send_at


def test_sequence_348_keeps_professional_entry_and_stop_contracts():
    text = _text()
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert "TZ39_InitialEntryReady" in evaluate
    assert "TZ35_ReentryEntryReady" in evaluate
    assert "TZ36_PostHandoffEntryReady" in evaluate
    assert "TZ46_InitialZoneProtectedStop" in evaluate
    assert 'TZ_SetGate("TARGET","MIN_RR_NOT_MET")' in evaluate
    assert "TZ47_TryAlternativePrimary" in evaluate
    assert "TZ47_TryAlternativeReentry" in evaluate


def test_sequence_348_loads_runway_contract_on_cloud_refresh():
    text = _text()
    refresh = text[text.index("bool TZ31_RefreshCloudState"):text.index("void TZ_WriteSequenceState")]
    for needle in (
        'StringToDouble(KV(text,"required_runway"))',
        'StringToDouble(KV(text,"usable_runway_target"))',
        'StringToDouble(KV(text,"runway_entry_limit"))',
        'KV(text,"runway_gate_mode")',
        "TZ48_LoadRunwayContract(text)",
    ):
        assert needle in text
    assert "TZ48_LoadRunwayContract(text)" in refresh


def test_sequence_348_persists_runway_telemetry():
    text = _text()
    for needle in (
        '"required_runway="',
        '"runway_target="',
        '"runway_entry_limit="',
        '"runway_gate_mode="',
        '"last_actual_entry_runway="',
    ):
        assert needle in text


def test_sequence_348_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
