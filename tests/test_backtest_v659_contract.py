from pathlib import Path
import ast
import csv

from app import backtest


MQL = Path("mt5/backtest/InstitutionalSMC_SequenceEA_v3_42_MasterSniper_Backtest_Demo.mq5")


def test_replay_contract_has_exact_legacy_geometry_and_sidecar_widths():
    assert len(backtest.PLAN_FIELDS) == 21
    assert backtest.PLAN_FIELDS[:5] == ["epoch", "analysis_id", "zone_id", "ea_mode", "grade"]
    assert len(backtest.CONTRACT_FIELDS) == 24
    for field in (
        "thesis_key",
        "execution_authority",
        "current_grade",
        "qualified_mitigations",
        "risk_context",
        "base_risk_pct",
        "original_risk_pct",
        "flip_risk_pct",
        "contract_fingerprint",
    ):
        assert field in backtest.CONTRACT_FIELDS


def test_closed_before_never_exposes_unclosed_bar():
    rows = [
        backtest.ReplayBar(ts=0, open=1, high=1, low=1, close=1),
        backtest.ReplayBar(ts=900, open=2, high=2, low=2, close=2),
        backtest.ReplayBar(ts=1800, open=3, high=3, low=3, close=3),
    ]
    series = backtest.BarSeries(rows)
    assert [b.ts for b in series.closed_before(899, "M15", 10)] == []
    assert [b.ts for b in series.closed_before(900, "M15", 10)] == [0]
    assert [b.ts for b in series.closed_before(1799, "M15", 10)] == [0]
    assert [b.ts for b in series.closed_before(1800, "M15", 10)] == [0, 900]


def test_plan_rows_use_current_grade_and_exact_contract_authority():
    class A:
        analysis_id = "A1"
        execution_policy = {
            "active_thesis": {
                "locked": True,
                "owner_zone_id": "Z1",
                "ownership_acquired_at": 123,
            }
        }

    text = "\n".join(
        [
            "analysis_id=A1",
            "zone_id=Z1",
            "ea_mode=DUAL_BRANCH",
            "grade=A+",
            "current_grade=A",
            "qualified_mitigations=1",
            "original_direction=SELL",
            "flip_direction=BUY",
            "core_low=4300",
            "core_high=4305",
            "zone_low=4298",
            "zone_high=4307",
            "original_target1=4280",
            "original_target2=4270",
            "original_target3=4260",
            "original_runner=4250",
            "flip_target1=4310",
            "flip_target2=4320",
            "flip_target3=4330",
            "flip_runner=4340",
            "min_displacement_atr=0.8",
            "min_rr=1.5",
            "execution_authority=HTF_ZONE_SWEEP_HANDOFF",
            "risk_context=TREND",
            "base_risk_pct=0.75",
            "original_risk_pct=0.75",
            "flip_risk_pct=0.50",
            "validation_initial_capital=10000",
            "setup_type=CONTINUATION",
            "zone_state=ACTIVE",
            "core_method=MASTER_SNIPER_SOURCE_EXACT",
            "contract_fingerprint=abc123",
            "sniper_parity_version=SNIPER_PARITY_V1",
        ]
    ) + "\n"
    plan, contract = backtest._plan_rows(1000, "TEST", A(), None, text)
    assert plan["grade"] == "A"
    assert contract["current_grade"] == "A"
    assert contract["execution_authority"] == "HTF_ZONE_SWEEP_HANDOFF"
    assert contract["qualified_mitigations"] == 1
    assert contract["thesis_key"] == "OWNER|Z1|123"
    assert contract["contract_fingerprint"] == "abc123"


def test_service_replay_hook_is_keyword_only_and_live_compatible():
    source = Path("app/service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_analysis")
    assert fn.args.args[0].arg == "reason"
    kw = [x.arg for x in fn.args.kwonlyargs]
    assert kw == ["snapshot", "as_of_ts", "ai_validator"]
    assert "validator = ai_validator or validate_with_ai" in source


def test_mql_backtest_harness_uses_sidecar_authority_and_does_not_modify_stable_file():
    text = MQL.read_text(encoding="utf-8")
    assert 'TZ_BACKTEST_CONTRACT "MASTER_SNIPER_V659_NO_LOOKAHEAD_REPLAY_V1"' in text
    assert 'input string TesterContractFile="SMC_v659_tester_plans_contract.csv";' in text
    assert "TZBT_LoadTesterContracts" in text
    assert "TZBT_FindContract" in text
    assert "g_tzExecutionAuthority=(c.execution_authority" in text
    assert "g_tzQualifiedMitigations=c.qualified_mitigations" in text
    assert "g_tzOriginalRiskPct=(c.original_risk_pct>0?c.original_risk_pct:c.base_risk_pct)" in text
    assert 'if(IsTester()){RefreshPlan();return;}' in text
    assert 'if(IsTester())\n   {\n      return RefreshPlan();\n   }' in text
    assert 'if(IsTester())return;\n   string p=TZ_StatePrefix();' in text
    stable = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_42_SniperContractParity_Demo.mq5").read_text(encoding="utf-8")
    assert "TesterContractFile" not in stable


def test_mt5_style_date_time_headers_are_accepted(tmp_path):
    path = tmp_path / "XAU_M1.csv"
    path.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\n"
        "2026.09.25\t10:40:00\t4293.0\t4294.0\t4292.5\t4293.5\t123\n",
        encoding="utf-8",
    )
    series = backtest.read_bars(path)
    assert len(series.rows) == 1
    assert series.rows[0].close == 4293.5
    assert series.rows[0].tick_volume == 123.0
