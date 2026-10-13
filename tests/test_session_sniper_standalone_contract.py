from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "mt5" / "standalone" / "SessionSniperEA_v0_12_NoTimeout_7030Runner_Demo.mq5"
DOC = ROOT / "docs" / "SESSION_SNIPER_STANDALONE_V0_10.md"


def test_session_sniper_is_standalone_and_demo_only():
    src = EA.read_text(encoding="utf-8")
    assert '#property version   "1.12"' in src
    assert "ACCOUNT_TRADE_MODE_DEMO" in src
    assert "InpMagicNumber=6510010" in src
    assert "InstitutionalSMC_SequenceEA" not in src
    assert "SniperContractParityV1" not in src
    assert "/mt5/plan" not in src
    assert "/mt5/heartbeat" not in src


def test_session_sniper_requires_external_liquidity_and_full_m1_sequence():
    src = EA.read_text(encoding="utf-8")
    assert "ARMED_EXTERNAL_LIQUIDITY_REQUIRED" in src
    assert "BUY_EXTERNAL_SSL_SWEPT" in src
    assert "SELL_EXTERNAL_BSL_SWEPT" in src
    assert "REFERENCE_RECLAIM" in src
    assert "MSS_DISPLACEMENT" in src
    assert "BREAKER_RETEST" in src
    assert "InpMinRR=2.0" in src


def test_session_sniper_has_london_ny_dst_and_one_trade_per_session_contract():
    src = EA.read_text(encoding="utf-8")
    assert "LondonDstForLocalDate" in src
    assert "NewYorkDstForLocalDate" in src
    assert 's.name=="NEW_YORK"' in src
    assert "if(s.traded || s.stage==SS_DONE) return;" in src
    assert "InpStopAfterFirstWinningTrade=true" in src


def test_session_sniper_documentation_exists():
    text = DOC.read_text(encoding="utf-8")
    assert "London + New York" in text
    assert "external-liquidity" in text
    assert "does **not** replace, modify, or share execution state" in text


def test_session_sniper_7030_management_and_installer_isolation():
    src = EA.read_text(encoding="utf-8")
    installer = (ROOT / "mt5" / "standalone" / "Install_SessionSniper_MT5.ps1").read_text(encoding="utf-8")
    assert "InpPartialPercent=70.0" in src
    assert "InpRunnerPercent=30.0" in src
    assert "SplitVolume7030" in src
    assert 'partial_comment="SS "+s.name+" P70"' in src
    assert 'runner_comment="SS "+s.name+" R30"' in src
    assert "ManageRunnerTrail" in src
    assert "LatestProtectedTrailSwing" in src
    assert "SessionSniperEA_v0_11_7030Runner_Demo.mq5" in installer
    assert "Sequence 3.78 system" in installer
    assert "Experts\\TradeZone\\SessionSniper" in installer


def test_session_sniper_has_no_arbitrary_setup_timeout_and_runner_has_no_hard_tp():
    src = EA.read_text(encoding="utf-8")
    assert "InpExecutionEndHourLocal" not in src
    assert "InpExecutionEndMinuteLocal" not in src
    assert "InpMaxMinutesSweepToMSS" not in src
    assert "InpMaxMinutesMssToRetest" not in src
    assert "SWEEP_TO_MSS_EXPIRED" not in src
    assert "BREAKER_RETEST_EXPIRED" not in src
    assert "runner_tp=NONE" in src
    assert "BUY_OBJECTIVE_REACHED_BEFORE_ENTRY" in src
    assert "SELL_OBJECTIVE_REACHED_BEFORE_ENTRY" in src
