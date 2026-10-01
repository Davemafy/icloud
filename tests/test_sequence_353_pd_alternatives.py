from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_53_PDAlternatives_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def test_sequence_353_promotes_ob_or_fvg_retest_semantics():
    text = _text()
    assert '#property version   "3.53"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.53"' in text
    assert "TZ53_FindRetestedPostMssPD" in text
    assert "Model 1 explicitly accepts OB OR FVG" in text
    assert 'pdType="FVG";return true;' in text
    assert 'pdType="OB";return true;' in text


def test_sequence_353_keeps_micro_mss_and_no_chase_confirmation():
    text = _text()
    assert "TZ51_FindNearestMicroSwing" in text
    assert "TZ50_BuildSniperPD" in text
    assert "TZ50_BuildZoneEngulfing" in text
    assert "TZ50_BarTouchesRange(r[pullbackIdx],lo,hi)" in text
    assert "bool directional=buy?(r[1].close>r[1].open):(r[1].close<r[1].open);" in text
    assert "bool structureHeld=buy?(r[1].close>mss):(r[1].close<mss);" in text


def test_sequence_353_diagnostic_uses_same_pd_alternative_selector():
    text = _text()
    diagnose = text[text.index("string TZ50_DiagnoseSniper"):text.index("\nvoid TZ_ShallowValue", text.index("string TZ50_DiagnoseSniper"))]
    assert "TZ53_FindRetestedPostMssPD" in diagnose
    assert 'return "M1_PD_PULLBACK";' in diagnose
    assert 'return "M1_DIRECTIONAL_CLOSE";' in diagnose


def test_sequence_353_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
