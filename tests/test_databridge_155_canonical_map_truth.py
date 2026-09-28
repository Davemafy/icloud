from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_55_CanonicalMapTruth.mq5"
RENDERER = ROOT / "mt5/stable/TradeZone_ZoneRenderer_v1_0.mqh"


def test_bridge_155_uses_canonical_primary_renderer_map_truth():
    text = BRIDGE.read_text(encoding="utf-8")
    for needle in (
        '#property version "1.55"',
        '#define TZ_BRIDGE_VERSION "1.55"',
        '#define TZ_ZONE_RENDER_CONTRACT "V662"',
        'if(!g_tzrZones[i].valid || g_tzrZones[i].role!="PRIMARY")continue;',
        'sellState=g_tzrZones[i].state;',
        'buyState=g_tzrZones[i].state;',
        'SMC Cloud | HTF MAP ',
    ):
        assert needle in text, needle
    body = text.split("void TZ_ReadTwoZoneMap()", 1)[1].split("string TZ_SequenceExecutionDisplay()", 1)[0]
    assert 'Get("/analysis"' not in body
    assert 'StringFind(text,"\"zone_id\""'
    not in body


def test_bridge_155_chart_status_matches_final_watch_only_plan():
    text = BRIDGE.read_text(encoding="utf-8")
    assert 'if(stage=="AUTHORITY" && reason=="PLAN_WATCH_ONLY")return "CLOUD PLAN WATCH ONLY";' in text
    assert text.index("TZR_RefreshAndRender();") < text.index("TZ_ReadTwoZoneMap();")


def test_v662_renderer_humanizes_internal_map_states():
    text = RENDERER.read_text(encoding="utf-8")
    for needle in (
        "TZR_DisplayState",
        'if(state=="ARMED")return "MAP VALID / RETEST PENDING";',
        'if(state=="INTERACTING")return "CONTACTED / M1 PENDING";',
        'if(state=="M1_READY")return "M1 HANDOFF ACTIVE";',
        'if(state=="FLIP_CONTEXT")return "FLIP CONTEXT";',
        'string display_state=TZR_DisplayState(z.state);',
    ):
        assert needle in text, needle
    assert 'label+=" | "+z.state;' not in text


def test_bridge_155_sources_are_structurally_balanced():
    for path in (BRIDGE, RENDERER):
        text = path.read_text(encoding="utf-8")
        for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
            assert text.count(left) == text.count(right), (path.name, left, right)
