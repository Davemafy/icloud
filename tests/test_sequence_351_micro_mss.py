from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_51_MicroSwingMSS_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def test_sequence_351_uses_nearest_m1_micro_swing_for_mss():
    text = _text()
    assert '#property version   "3.51"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.51"' in text
    assert "TZ51_FindNearestMicroSwing" in text
    assert "Nearest one-minute internal swing" in text
    assert text.count("TZ51_FindNearestMicroSwing(r,sw,buy,microDepth,ms,mss)") == 2


def test_sequence_351_model1_no_longer_uses_old_five_bar_pivot_for_mss():
    text = _text()
    builder = text[text.index("bool TZ50_BuildSniperPD"):text.index("bool TZ50_BuildZoneEngulfing")]
    diagnostic = text[text.index("string TZ50_DiagnoseSniper"):text.index("void TZ_ShallowValue")]
    old = "OlderPivot(r,sw+2,lookEnd,buy,ms,mss)"
    assert old not in builder
    assert old not in diagnostic
    assert "OlderPivot(r,sw+2,lookEnd,!buy,li,liquidity)" in builder


def test_micro_swing_helper_is_intentionally_lighter_than_htf_style_fractal():
    text = _text()
    block = text[text.index("bool TZ51_FindNearestMicroSwing"):text.index("bool TZ50_BuildSniperPD")]
    assert "r[i].high>r[i-1].high && r[i].high>=r[i+1].high" in block
    assert "r[i].low<r[i-1].low && r[i].low<=r[i+1].low" in block
    assert "sweepIdx+3" in block


def test_existing_two_sniper_models_and_risk_guards_remain_intact():
    text = _text()
    assert "TZ50_BuildSniperPD" in text
    assert "TZ50_BuildZoneEngulfing" in text
    assert "TZ46_InitialZoneProtectedStop" in text
    assert "TZ36_MinRRValid" in text
    assert "TZ42_RevalidateParityBeforeOrder" in text


def test_sequence_351_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
