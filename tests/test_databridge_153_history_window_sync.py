from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_53_HistoryWindowSync.mq5"
CORE = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_32_XAU_DXY_Journal.mq5"


def test_bridge_153_uses_history_aware_core_and_current_sequence():
    text = BRIDGE.read_text(encoding="utf-8")
    assert '#property version "1.53"' in text
    assert '#define TZ_BRIDGE_VERSION "1.53"' in text
    assert '#define TZ_SEQUENCE_EXPECTED "3.45"' in text
    assert "InstitutionalSMC_DataBridge_v1_32_XAU_DXY_Journal.mq5" in text
    assert "history_window_failures=" in text
    assert "history_window_metrics=" in text


def test_core_132_uses_calendar_safe_effective_minimums_and_refuses_partial_snapshot():
    text = CORE.read_text(encoding="utf-8")
    for needle in (
        '#property version "1.32"',
        'input int BarsD1=390;',
        'input int BarsH4=900;',
        'input int BarsH1=900;',
        'input int BarsM15=800;',
        'if(tf==PERIOD_D1)count=MathMax(count,390);',
        'else if(tf==PERIOD_H4)count=MathMax(count,900);',
        'else if(tf==PERIOD_H1)count=MathMax(count,900);',
        'else if(tf==PERIOD_M15)count=MathMax(count,800);',
        'TZ_PrimeHistory',
        '350.0,0,400',
        '120.0,0,150',
        '28.0,0,45',
        '0.0,3,10',
        'g_tzHistoryFailures',
        'if(!historyReady)',
        'return false;',
        '\"protocol\":7',
    ):
        assert needle in text, needle


def test_bridge_sources_are_structurally_balanced():
    for path in (BRIDGE, CORE):
        text = path.read_text(encoding="utf-8")
        for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
            assert text.count(left) == text.count(right), (path.name, left, right)
