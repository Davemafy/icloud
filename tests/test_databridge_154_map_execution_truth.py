from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_54_MapExecutionTruth.mq5"
RENDERER = ROOT / "mt5/stable/TradeZone_ZoneRenderer_v1_0.mqh"


def test_bridge_154_separates_htf_map_state_from_execution_readiness():
    text = BRIDGE.read_text(encoding="utf-8")
    for needle in (
        '#property version "1.54"',
        '#define TZ_BRIDGE_VERSION "1.54"',
        '#define TZ_SEQUENCE_EXPECTED "3.45"',
        '#define TZ_ZONE_RENDER_CONTRACT "V661"',
        'TZ_MapDisplayState',
        'MAP VALID / RETEST PENDING',
        'CONTACTED / M1 PENDING',
        'M1 HANDOFF ACTIVE',
        'MAP WATCH / NO ENTRY AUTHORITY',
        'SMC Cloud | HTF MAP ',
    ):
        assert needle in text, needle


def test_bridge_154_keeps_invalidated_zone_as_zero_authority_flip_context_message():
    text = BRIDGE.read_text(encoding="utf-8")
    for needle in (
        'TZ_FlipContextSummary',
        'g_tzrZones[i].state!="FLIP_CONTEXT"',
        'INVALIDATED "+original+" -> "+flip+" FLIP CONTEXT',
        'RETEST + M1 REQUIRED',
    ):
        assert needle in text, needle


def test_v661_renderer_uses_non_misleading_lifecycle_labels():
    text = RENDERER.read_text(encoding="utf-8")
    assert 'label+=" | THESIS OWNER";' in text
    assert 'label+=" | M1 HANDOFF | SEQUENCE GATE REQUIRED";' in text
    assert 'label+=" | MAP CONTEXT";' in text
    assert 'label+=" | EXECUTION";' not in text


def test_bridge_154_sources_are_structurally_balanced():
    for path in (BRIDGE, RENDERER):
        text = path.read_text(encoding="utf-8")
        for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
            assert text.count(left) == text.count(right), (path.name, left, right)
