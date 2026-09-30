from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_49_SimpleMicroMSS_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def _evaluate(text: str) -> str:
    start = text.index("void Evaluate()")
    return text[start:text.index("\nint OnInit()", start)]


def test_sequence_349_primary_is_simple_m1_micro_mss_model():
    text = _text()
    evaluate = _evaluate(text)

    assert '#property version   "3.49"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.49"' in text
    assert "HTF_ZONE_CONTACT_HANDOFF" in evaluate
    assert "TZ49_BuildSimplePrimary" in evaluate
    assert 'g_tzCandidateModel="MASTER_SNIPER_SIMPLE"' in evaluate

    builder = text[text.index("bool TZ49_BuildSimplePrimary"):text.index("string TZ49_DiagnoseSimplePrimary")]
    assert "TouchZone(r[sw])" in builder
    assert "r[sw].low<liquidity-buf" in builder
    assert "r[sw].high>liquidity+buf" in builder
    assert "r[j].close>mss" in builder
    assert "r[j].close<mss" in builder
    assert "bool retraced=" in builder
    assert "r[1].close>r[1].open" in builder
    assert "r[1].close<r[1].open" in builder
    assert "StrongDisp(" not in builder
    assert "FindFreshPD(" not in builder
    assert "OTE(" not in builder


def test_sequence_349_primary_does_not_reapply_old_value_confirmation_or_runway_veto():
    text = _text()
    evaluate = _evaluate(text)

    simple_confirm = evaluate[evaluate.index('bool simplePrimary=(sig.pd_type=="MASTER_SNIPER_SIMPLE")'):]
    assert "valueReactionIdx=1" in simple_confirm
    assert "TZ48_EntrySpecificRunwayValid" not in evaluate
    assert "MIN_RR_NOT_MET_TO_DEEPEST_OPEN_OBJECTIVE" in evaluate
    assert "TZ49_DeepestDirectionalTarget" in evaluate


def test_sequence_349_keeps_full_zone_buffered_stop_and_filters_consumed_targets():
    text = _text()
    evaluate = _evaluate(text)

    assert "TZ46_InitialZoneProtectedStop" in evaluate
    assert "TZ49_OpenDirectionalTargets" in text
    assert "TZ49_OpenDirectionalTargets(flip,buy,entry,t1,t2,t3,run)" in text
    assert "TZ49_DeepestDirectionalTarget" in evaluate

    target_filter = text[text.index("int TZ49_OpenDirectionalTargets"):text.index("bool TZ49_DeepestDirectionalTarget")]
    assert "x>entry+gap" in target_filter
    assert "x<entry-gap" in target_filter


def test_sequence_349_primary_alternative_models_default_off():
    text = _text()
    for needle in (
        "input bool ResearchAllowContinuationRescue=false;",
        "input bool ResearchAllowEscapePullback=false;",
        "input bool EnableAlternativePrimary=false;",
        "input bool EnableMomentumPullbackModel=false;",
        "input bool EnableVWAPProxyModel=false;",
        "input bool EnableOpeningRangeRetestModel=false;",
    ):
        assert needle in text


def test_sequence_349_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
