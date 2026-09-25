from pathlib import Path


LAB = Path("mt5/installer/TradeZone_MasterSniper_Backtest_Lab.ps1")
LAB_BAT = Path("mt5/installer/TradeZone_MasterSniper_Backtest_Lab.bat")


def test_integrated_lab_compiles_exports_replays_and_prepares_real_tick_test():
    text = LAB.read_text(encoding="utf-8")
    for required in (
        "TradeZone_MasterSniper_HistoryExporter.mq5",
        "InstitutionalSMC_SequenceEA_v3_42_MasterSniper_Backtest_Demo.mq5",
        "CompileOne $meta $exportSrc",
        "CompileOne $meta $backtestSrc",
        "TradeZoneBacktest\\\\MasterSniperV659Runs\\\\",
        "/validation/backtest/v659/jobs",
        "Cloud replay status:",
        "Cloud replay progress:",
        "processed_m1_closes",
        "total_m1_closes",
        "progress_pct",
        "/download",
        "SMC_v6_tester_plans.csv",
        "SMC_v659_tester_plans_contract.csv",
        "MASTER_SNIPER_V659_NO_LOOKAHEAD_REPLAY_V1",
        "Model=4",
        "FromUnixTimeSeconds($startEpoch)",
        "FromUnixTimeSeconds($endEpoch)",
        "'XAU_D1.csv_rows'=80",
        "'XAU_H4.csv_rows'=120",
        "'XAU_H1.csv_rows'=160",
        "'XAU_M15.csv_rows'=160",
        "'DXY_D1.csv_rows'=60",
        "'DXY_H4.csv_rows'=80",
        "'DXY_H1.csv_rows'=100",
        "USD economic-calendar history is empty",
        "Optimization=0",
        "UseRemote=0",
        "UseCloud=0",
        "Collect_MasterSniper_Backtest_Results.bat",
        "MasterSniper_v659_tester_journal.csv",
        "MasterSniper_v659_tester_summary.txt",
        "MasterSniper_Backtest_Result.zip",
        "Live DataBridge 1.51 / Sequence 3.42 were never replaced or detached.",
    ):
        assert required in text


def test_integrated_lab_uses_managed_cloud_credentials_without_embedding_them():
    text = LAB.read_text(encoding="utf-8")
    assert "TradeZoneMT5\\config.json" in text
    assert "$cfg.cloud_url" in text
    assert "$cfg.cloud_api_key" in text
    assert "@{'X-API-Key'=$apiKey}" in text
    assert "change-me" not in text


def test_integrated_lab_launcher_targets_main_after_deployment():
    text = LAB_BAT.read_text(encoding="utf-8")
    assert "raw.githubusercontent.com/Davemafy/icloud/main/" in text
    assert "TradeZone_MasterSniper_Backtest_Lab.ps1" in text


def test_backtest_lab_does_not_modify_stable_manifest_or_live_ea_paths():
    text = LAB.read_text(encoding="utf-8")
    assert "mt5/stable/manifest.json" not in text
    assert "Experts\\TradeZoneValidation" in text
    assert "Scripts\\TradeZoneValidation" in text



def test_each_lab_run_uses_fresh_export_directory_and_stages_before_zip():
    text = LAB.read_text(encoding="utf-8")
    assert "MasterSniperV659Runs" in text
    assert "$runToken=(Get-Date).ToString" in text
    assert "$relativeExportDir" in text
    assert "CopyWithRetry" in text
    assert "$uploadStaging=Join-Path $tmp 'history_upload'" in text
    assert "Compress-Archive -Path (Join-Path $uploadStaging '*')" in text
    assert "Remove-Item $exportDir -Recurse -Force" not in text
