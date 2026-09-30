from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_50_SniperPD_Engulfing_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def _evaluate(text: str) -> str:
    start = text.index("void Evaluate()")
    return text[start:text.index("\nint OnInit()", start)]


def test_sequence_350_exposes_two_primary_sniper_models():
    text = _text()
    assert '#property version   "3.50"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.50"' in text
    assert "TZ50_BuildSniperPD" in text
    assert "TZ50_FindPostMssPD" in text
    assert 'sig.pd_type="MASTER_SNIPER_PD_"+pt' in text
    assert "TZ50_BuildZoneEngulfing" in text
    assert 'sig.pd_type="ZONE_ENGULFING"' in text


def test_model1_is_m1_sweep_micro_mss_obfvg_pullback_close_without_ote_or_displacement():
    text = _text()
    block = text[text.index("bool TZ50_BuildSniperPD"):text.index("bool TZ50_BuildZoneEngulfing")]
    assert "TouchZone(r[sw])" in block
    assert "OlderPivot" in block
    assert "r[j].close>mss" in block
    assert "r[j].close<mss" in block
    assert "TZ50_FindPostMssPD" in block
    assert "TZ50_BarTouchesRange(r[2],pl,ph)" in block
    assert "r[1].close>r[1].open" in block
    assert "r[1].close<r[1].open" in block
    assert "StrongDisp(" not in block
    assert "OTE(" not in block

    pd = text[text.index("bool TZ50_FindPostMssPD"):text.index("bool TZ50_BuildSniperPD")]
    assert 'pdType="FVG"' in pd
    assert 'pdType="OB"' in pd
    assert "EnableFVG" in pd
    assert "EnableOrderBlock" in pd


def test_model2_is_closed_directional_real_body_engulfing_at_zone():
    text = _text()
    block = text[text.index("bool TZ50_BuildZoneEngulfing"):text.index("bool TZ50_TrySniperModels")]
    assert "!TouchZone(r[1])&&!TouchZone(r[2])" in block
    assert "prevOpp" in block
    assert "nowDir" in block
    assert "nowLo<=prevLo+tol&&nowHi>=prevHi-tol" in block
    assert "StrongDisp(" not in block
    assert "OlderPivot(" not in block


def test_primary_models_rearm_for_r1_r2_instead_of_old_reentry_builder():
    text = _text()
    evaluate = _evaluate(text)
    assert "g_primaryEntries>0&&EnableReentries" in evaluate
    assert "TZ50_TrySniperModels(r,origBuy,true,sig,sniperModel)" in evaluate
    assert 'tag="R"+IntegerToString(g_reentries+1)' in evaluate
    primary_section = evaluate[evaluate.index("bool primaryAuthority="):evaluate.index("if(!sig.valid)")]
    assert "BuildReentry(r,a,origBuy,sig)" not in primary_section.split('else if(g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF"')[0]


def test_sniper_r1_r2_keep_full_zone_buffered_stop():
    text = _text()
    evaluate = _evaluate(text)
    assert "zoneProtectedSniper" in evaluate
    assert 'StringFind(sig.pd_type,"MASTER_SNIPER_PD_")==0' in evaluate
    assert 'sig.pd_type=="ZONE_ENGULFING"' in evaluate
    assert "TZ46_InitialZoneProtectedStop" in evaluate


def test_sequence_350_retains_rr_and_safety_gates():
    text = _text()
    evaluate = _evaluate(text)
    assert "TZ36_MinRRValid" in evaluate
    assert "TZ49_DeepestDirectionalTarget" in evaluate
    assert "TZ42_RevalidateParityBeforeOrder" in evaluate
    assert "TZ37_LotsForRisk" in evaluate
    assert "TZ48_EntrySpecificRunwayValid" not in evaluate


def test_sequence_350_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
