from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_46_ZoneDistalStop_Demo.mq5")


def test_sequence_346_version_and_zone_distal_stop_contract():
    text = SEQ.read_text(encoding="utf-8")
    assert '#property version   "3.46"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.46"' in text
    assert "double TZ46_ZoneStopBuffer(double m1Atr)" in text
    assert "double TZ46_InitialZoneProtectedStop(" in text
    assert "spreadBuffer=MathMax(0.0,tk.ask-tk.bid)*1.50;" in text
    assert "double atrBuffer=(m1Atr>0?m1Atr*SLBufferATR:0.0);" in text
    assert "return MathMax(MathMax(point*5.0,spreadBuffer),MathMax(atrBuffer,brokerBuffer));" in text
    assert "double zoneStop=buy?(zoneLow-buffer):(zoneHigh+buffer);" in text
    assert "double out=buy?MathMin(microStop,zoneStop):MathMax(microStop,zoneStop);" in text


def test_first_entries_use_full_zone_distal_stop_and_reentries_keep_local_structure():
    text = SEQ.read_text(encoding="utf-8")
    normal = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    assert "double microSl=sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR;" in normal
    assert "double sl=sig.reentry" in normal
    assert "?NormalizeDouble(microSl,_Digits)" in normal
    assert ":TZ46_InitialZoneProtectedStop(sig.buy,microSl,g_plan.zone_low,g_plan.zone_high,a);" in normal
    assert 'TZ_SetGate("RISK","ZONE_DISTAL_STOP_UNAVAILABLE")' in normal

    flip = text[text.index("void TZ28_EvaluateAcceptedFlip()"):text.index("\nstring TZ_JsonEscape", text.index("void TZ28_EvaluateAcceptedFlip()"))]
    assert 'double sl=(tag=="F0")' in flip
    assert "TZ46_InitialZoneProtectedStop(sig.buy,microSl,g_tzFlipPlan.zone_low,g_tzFlipPlan.zone_high,a)" in flip
    assert 'TZ_SetGate("RISK","FLIP_ZONE_DISTAL_STOP_UNAVAILABLE")' in flip


def test_zone_distal_stop_is_applied_before_rr_and_order_sizing():
    text = SEQ.read_text(encoding="utf-8")
    normal = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    stop_at = normal.index("TZ46_InitialZoneProtectedStop")
    rr_at = normal.index("TZ36_MinRRValid")
    sizing_at = normal.index("TZ37_LotsForRisk")
    send_at = normal.index("TZ37_SendOrders")
    assert stop_at < rr_at < sizing_at < send_at
    assert 'TZ_SetGate("TARGET","MIN_RR_NOT_MET")' in normal


def test_sequence_346_source_is_structurally_balanced():
    text = SEQ.read_text(encoding="utf-8")
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
