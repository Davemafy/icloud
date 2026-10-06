from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_59_DisplayTruth.mq5"
CORE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_33_StrategicEntryJournal.mq5"


def test_bridge_159_tracks_sequence_372_and_uses_dynamic_startup_truth():
    text = BRIDGE.read_text(encoding="utf-8")
    for needle in (
        '#property version "1.59"',
        '#define TZ_JOURNAL_BRIDGE_VERSION "1.33"',
        '#define TZ_BRIDGE_VERSION "1.59"',
        '#define TZ_SEQUENCE_EXPECTED "3.72"',
        'InstitutionalSMC_DataBridge_v1_33_StrategicEntryJournal.mq5',
        'Sequence ",TZ_SEQUENCE_EXPECTED," execution-context display truth',
    ):
        assert needle in text, needle
    assert "Sequence 3.47 strategic multi-model execution truth" not in text
    assert "Sequence 3.48 actual-entry runway truth" not in text


def test_bridge_159_flip_overlay_distinguishes_active_execution_from_history():
    text = BRIDGE.read_text(encoding="utf-8")
    fn_start = text.index("string TZ_FlipContextSummary()")
    fn_end = text.index("void TZ_ReadTwoZoneMap()", fn_start)
    fn = text[fn_start:fn_end]
    assert 'execution_context_type' in fn
    assert 'execution_context_zone_id' in fn
    assert 'execution_context_direction' in fn
    assert 'execution_context_slot' in fn
    assert 'acceptedFlipActive=(executionContext=="ACCEPTED_ZONE_FLIP")' in fn
    assert '"ACTIVE ACCEPTED "+flip+" FLIP"' in fn
    assert '"HISTORICAL INVALIDATED "+original+" -> "+flip+' in fn
    assert '" FLIP | CONTEXT ONLY | NO CURRENT M1 AUTHORITY"' in fn
    assert 'item+=" | SOURCE "+g_tzrZones[i].id+" | RETEST + M1 REQUIRED";' in fn


def test_bridge_159_does_not_require_retest_for_dormant_flip_context():
    text = BRIDGE.read_text(encoding="utf-8")
    fn_start = text.index("string TZ_FlipContextSummary()")
    fn_end = text.index("void TZ_ReadTwoZoneMap()", fn_start)
    fn = text[fn_start:fn_end]
    historical = fn.index('"HISTORICAL INVALIDATED "')
    active_retest = fn.index('" | SOURCE "+g_tzrZones[i].id+" | RETEST + M1 REQUIRED"')
    assert active_retest < historical
    # The old unconditional suffix must be gone.
    assert 'if(out!="")out+=" | RETEST + M1 REQUIRED";' not in fn


def test_bridge_159_sources_are_structurally_balanced():
    for path in (BRIDGE, CORE):
        text = path.read_text(encoding="utf-8")
        for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
            assert text.count(left) == text.count(right), (path.name, left, right)
