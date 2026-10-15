from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "mt5" / "standalone" / "SessionSniperEA_v0_15_InformationPanel_Demo.mq5"
DOC = ROOT / "docs" / "SESSION_SNIPER_STANDALONE_V0_10.md"
INSTALLER = ROOT / "mt5" / "standalone" / "Install_SessionSniper_MT5.ps1"


def test_session_sniper_is_standalone_demo_only_and_v015():
    src = EA.read_text(encoding="utf-8")
    assert '#property version   "1.15"' in src
    assert "ACCOUNT_TRADE_MODE_DEMO" in src
    assert "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING" in src
    assert "InpMagicNumber=6510010" in src
    assert "InstitutionalSMC_SequenceEA" not in src
    assert "/mt5/plan" not in src
    assert "/mt5/heartbeat" not in src


def test_reference_clock_is_0800_session_local_and_dst_aware():
    src = EA.read_text(encoding="utf-8")
    assert "InpReferenceHourLocal=8" in src
    assert "InpReferenceMinuteLocal=0" in src
    assert "InpReferenceMinutes=60" in src
    assert "LondonDstForLocalDate" in src
    assert "NewYorkDstForLocalDate" in src
    assert "SessionUtcOffsetSeconds" in src


def test_nearest_external_reference_can_be_swing_or_unfilled_fvg():
    src = EA.read_text(encoding="utf-8")
    assert "SS_EXT_SWING" in src
    assert "SS_EXT_FVG" in src
    assert "SS_EXT_FVG_SWING_CLUSTER" in src
    assert "ARMED_NEAREST_H1_SWING_OR_FVG" in src
    assert "remaining_prox" in src
    assert "fully_filled" in src
    assert "fvg_low_prox>=swing_low" in src
    assert "fvg_high_prox<=swing_high" in src
    assert "EXT_LOW_FVG_DISTAL" in src
    assert "EXT_HIGH_FVG_DISTAL" in src


def test_full_closed_m1_confirmation_sequence_remains_required():
    src = EA.read_text(encoding="utf-8")
    assert "EXTERNAL_SWEEP" in src
    assert "REFERENCE_RECLAIM" in src
    assert "MSS_DISPLACEMENT" in src
    assert "BREAKER_RETEST" in src
    assert "InpMinDisplacementATR=0.60" in src
    assert "InpMinRR=2.0" in src


def test_no_arbitrary_setup_timeout():
    src = EA.read_text(encoding="utf-8")
    assert "InpExecutionEndHourLocal" not in src
    assert "InpExecutionEndMinuteLocal" not in src
    assert "InpMaxMinutesSweepToMSS" not in src
    assert "InpMaxMinutesMssToRetest" not in src
    assert "SWEEP_TO_MSS_EXPIRED" not in src
    assert "BREAKER_RETEST_EXPIRED" not in src
    assert "BUY_OBJECTIVE_REACHED_BEFORE_ENTRY" in src
    assert "SELL_OBJECTIVE_REACHED_BEFORE_ENTRY" in src


def test_7030_management_runner_is_trail_only():
    src = EA.read_text(encoding="utf-8")
    assert "InpPartialPercent=70.0" in src
    assert "InpRunnerPercent=30.0" in src
    assert "SplitVolume7030" in src
    assert 'partial_comment="SS "+s.name+" P70"' in src
    assert 'runner_comment="SS "+s.name+" R30"' in src
    assert "runner_tp=NONE" in src
    assert "ManageRunnerTrail" in src
    assert "LatestProtectedTrailSwing" in src
    assert "InpStopAfterFirstWinningTrade=false" in src


def test_installer_remains_isolated_and_points_to_v015():
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "SessionSniperEA_v0_15_InformationPanel_Demo.mq5" in installer
    assert "Drag SessionSniperEA_v0_15_InformationPanel_Demo onto" in installer
    assert "Never run both versions together" in installer
    assert '#property version   "1.15"' in installer
    assert "Sequence 3.78 system" in installer
    assert "Experts\\TradeZone\\SessionSniper" in installer


def test_documentation_exists():
    text = DOC.read_text(encoding="utf-8")
    assert "London + New York" in text
    assert "does **not** replace, modify, or share execution state" in text


def test_information_panel_is_independent_and_current_day_only():
    src = EA.read_text(encoding="utf-8")
    assert "SS_DrawInformationPanel()" in src
    assert "SS_RemoveInformationPanel()" in src
    assert "SS_PanelStatus" in src
    assert "REFERENCE_DATA_INCOMPLETE" in src
    assert "SS_INFO_BACKGROUND" in src
    assert "SS_INFO_ROW_" in src
    assert "g_london.local_day_key" in src
    assert "g_newyork.local_day_key" in src
    assert "if(now<s.ref_end_server) return false;" in src
    assert "if(!s.reference_ready) return;" in src
    # The stable Sequence EA is not referenced or called by the new panel.
    assert "/mt5/plan" not in src
    assert "SendOrders" not in src
