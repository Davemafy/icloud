from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "mt5" / "standalone" / "SessionSniperEA_v0_17_QualifiedExternalTargets_Demo.mq5"
DOC = ROOT / "docs" / "SESSION_SNIPER_STANDALONE_V0_10.md"
INSTALLER = ROOT / "mt5" / "standalone" / "Install_SessionSniper_MT5.ps1"


def test_session_sniper_is_standalone_demo_only_and_v017():
    src = EA.read_text(encoding="utf-8")
    assert '#property version   "1.17"' in src
    assert "ACCOUNT_TRADE_MODE_DEMO" in src
    assert "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING" in src
    assert "InpMagicNumber=6510010" in src
    assert "InstitutionalSMC_SequenceEA" not in src
    assert "/mt5/plan" not in src
    assert "/mt5/heartbeat" not in src


def test_independent_london_0900_ny_0800_session_clock_and_dst():
    src = EA.read_text(encoding="utf-8")
    assert "InpLondonReferenceHourLocal=9" in src
    assert "InpLondonReferenceMinuteLocal=0" in src
    assert "InpNewYorkReferenceHourLocal=8" in src
    assert "InpNewYorkReferenceMinuteLocal=0" in src
    assert "InpReferenceMinutes=60" in src
    assert "reference_hour=london?InpLondonReferenceHourLocal:InpNewYorkReferenceHourLocal;" in src
    assert "reference_minute=london?InpLondonReferenceMinuteLocal:InpNewYorkReferenceMinuteLocal;" in src
    assert "LocalNaive(local_now,reference_hour,reference_minute)" in src
    assert "InpReferenceHourLocal=" not in src
    assert "InpReferenceMinuteLocal=" not in src
    assert "InpNewYorkCashOpenHourLocal=9" in src
    assert "InpNewYorkCashOpenMinuteLocal=30" in src
    assert 'SS_LocalReferenceLabel(true)' in src
    assert 'SS_LocalReferenceLabel(false)' in src
    assert "LondonDstForLocalDate" in src
    assert "NewYorkDstForLocalDate" in src
    assert "SessionUtcOffsetSeconds" in src


def test_nearest_external_reference_uses_unswept_h1_wick_or_fvg_distal():
    src = EA.read_text(encoding="utf-8")
    assert "SS_EXT_SWING" in src
    assert "SS_EXT_FVG" in src
    # Stronger swing: confirmed by two H1 candles on each side, and unswept.
    assert "for(int i=2;i<n-2;i++)" in src
    assert "h1[i].low<h1[i-2].low" in src
    assert "h1[i].low<h1[i+2].low" in src
    assert "h1[j].low<=h1[i].low" in src
    assert "h1[j].high>=h1[i].high" in src
    assert "h1[i].low<s.ref_low" in src
    assert "h1[i].high>s.ref_high" in src
    assert "if(!swept && h1[i].low>swing_low)" in src
    assert "if(!swept && h1[i].high<swing_high)" in src

    # FVG: the BOTTOM of bullish or TOP of bearish is the sweep objective;
    # later price action must not fully fill the gap.
    assert "double bull_bottom=h1[i-2].high;" in src
    assert "double bear_top=h1[i-2].low;" in src
    assert "if(h1[j].low<=bull_bottom)" in src
    assert "if(h1[j].high>=bear_top)" in src
    assert "if(s.ref_low<=bull_bottom)filled=true;" in src
    assert "if(s.ref_high>=bear_top)filled=true;" in src
    assert "fvg_low_objective=bull_bottom;" in src
    assert "fvg_high_objective=bear_top;" in src
    assert "if(swing_low_valid && (!fvg_low_valid || swing_low>=fvg_low_objective))" in src
    assert "if(swing_high_valid && (!fvg_high_valid || swing_high<=fvg_high_objective))" in src
    assert "s.ext_low=fvg_low_objective;" in src
    assert "s.ext_high=fvg_high_objective;" in src
    assert "s.ext_low_proximal=fvg_low_remaining_top;" in src
    assert "s.ext_high_proximal=fvg_high_remaining_bottom;" in src

    # Snapshot of the broker H1 candles must be completed BEFORE the reference.
    assert "h1[n-1].time+PeriodSeconds(PERIOD_H1)>s.ref_start_server" in src
    assert "if(n<7)" in src
    assert 's.last_reason="H1_DATA_INCOMPLETE";' in src
    assert "s.selection_audit=" in src
    assert 'JournalEvent(s,"REFERENCE_ARMED"' in src
    assert 'FileWriteString(h,"version=0.17' in src
    assert '"london_candidate_audit="' in src
    assert '"ny_candidate_audit="' in src
    assert "EXT_LOW_FVG_PROX" in src
    assert "EXT_HIGH_FVG_PROX" in src


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


def test_installer_remains_isolated_and_points_to_v017():
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "SessionSniperEA_v0_17_QualifiedExternalTargets_Demo.mq5" in installer
    assert "Drag SessionSniperEA_v0_17_QualifiedExternalTargets_Demo onto" in installer
    assert "Never run both versions together" in installer
    assert '#property version   "1.17"' in installer
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


def test_v015_rollback_source_retained_unchanged():
    previous=(ROOT / "mt5" / "standalone" / "SessionSniperEA_v0_15_InformationPanel_Demo.mq5").read_text(encoding="utf-8")
    assert '#property version   "1.15"' in previous
    assert "InpReferenceHourLocal=8" in previous


def test_documented_session_local_to_nigeria_dst_clock_contract():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    wat=ZoneInfo("Africa/Lagos")
    london=ZoneInfo("Europe/London")
    ny=ZoneInfo("America/New_York")
    for day,london_hour,new_york_hour in [(15,9,13)]:
        assert datetime(2026,10,day,9,tzinfo=london).astimezone(wat).hour==london_hour
        assert datetime(2026,10,day,8,tzinfo=ny).astimezone(wat).hour==new_york_hour
    assert datetime(2026,11,2,9,tzinfo=london).astimezone(wat).hour==10
    assert datetime(2026,11,2,8,tzinfo=ny).astimezone(wat).hour==14
