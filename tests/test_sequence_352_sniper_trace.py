from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_52_SniperTrace_Demo.mq5")
BRIDGE = Path("mt5/stable/InstitutionalSMC_DataBridge_v1_58_EntryRunwayTruth.mq5")
MAIN = Path("app/main.py")
DASH = Path("app/dashboard_view.py")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sequence_352_is_read_only_trace_layer_over_351_execution():
    text = _text(SEQ)
    assert '#property version   "3.52"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.52"' in text
    assert "TZ51_FindNearestMicroSwing" in text
    assert "TZ50_BuildSniperPD" in text
    assert "TZ50_BuildZoneEngulfing" in text
    assert "TZ52_ResetSniperTrace" in text
    assert "TZ52_CaptureSignalTrace" in text
    assert "TZ36_MinRRValid" in text
    assert "TZ46_InitialZoneProtectedStop" in text
    assert "TZ42_RevalidateParityBeforeOrder" in text


def test_trace_contains_exact_sweep_mss_pd_and_timestamps():
    text = _text(SEQ)
    for needle in (
        "trace_liquidity_level",
        "trace_sweep_price",
        "trace_sweep_ts",
        "trace_mss_level",
        "trace_mss_break_ts",
        "trace_pd_type",
        "trace_pd_low",
        "trace_pd_high",
        "trace_pd_ts",
        "trace_pullback_ts",
        "trace_confirm_ts",
    ):
        assert needle in text


def test_databridge_158_does_not_need_trace_schema_change():
    bridge = _text(BRIDGE)
    assert '#property version "1.58"' in bridge
    assert '#define TZ_BRIDGE_VERSION "1.58"' in bridge
    assert "trace_sweep_price" not in bridge
    assert "trace_mss_level" not in bridge


def test_cloud_passes_and_dashboard_renders_sequence_trace():
    main = _text(MAIN)
    dash = _text(DASH)
    for needle in (
        '"trace_sweep_price"',
        '"trace_mss_level"',
        '"trace_pd_low"',
        '"trace_pd_high"',
        '"trace_pullback_ts"',
    ):
        assert needle in main
    assert "M1 trace:" in dash
    assert "Micro MSS " in dash
    assert "PD pullback touched @" in dash


def test_sequence_352_source_is_structurally_balanced():
    text = _text(SEQ)
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)
