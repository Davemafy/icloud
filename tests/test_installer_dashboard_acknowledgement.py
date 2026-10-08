"""Installer-to-MT5-DataBridge-to-cloud dashboard version truth contract.

Installation is not cloud-confirmed merely because the source compiled.
The dashboard must acknowledge the unique install receipt reported by the
running DataBridge from the chosen MT5 data folder.
"""
from pathlib import Path

INSTALLER = Path("mt5/installer/Install_TradeZone_MT5.ps1")
BRIDGE = Path("mt5/stable/InstitutionalSMC_DataBridge_v1_59_DisplayTruth.mq5")
JOURNAL = Path("app/journal.py")
MAIN = Path("app/main.py")


def test_installer_writes_unique_receipt_to_correct_data_folder_after_compile():
    source = INSTALLER.read_text(encoding="utf-8")
    assert "Join-Path $t.MQL5 'Files\\TradeZone'" in source
    assert "$installReceipt='MANUAL_INSTALL_COMPILED_'+[guid]::NewGuid().ToString('N')" in source
    assert "'last_action='+$installReceipt" in source
    assert "installed_sequence_version='+[string]$m.sequence_ea_version" in source
    assert source.index("foreach($src in $srcs){CompileOne") < source.index("$installReceipt=")


def test_installer_checks_status_readback_and_exact_cloud_receipt():
    source = INSTALLER.read_text(encoding="utf-8")
    assert "$readBackLines=@(Get-Content -LiteralPath $statusFile -ErrorAction Stop)" in source
    assert "$readBackLines -notcontains $expected" in source
    assert "CheckDashboardAcknowledgement" in source
    assert "Invoke-RestMethod -Method Get -Uri $url" in source
    assert "'/system/status'" in source
    assert "$reportedReceipt=[string]$components.last_action" in source
    assert "$reportedReceipt -eq $InstallReceipt" in source
    assert "$reportedInstaller -eq $InstallerVersion" in source
    assert "$bridgeAge -le 45" in source
    assert "DASHBOARD ACKNOWLEDGEMENT PENDING" in source


def test_bridges_existing_last_action_heartbeat_to_both_status_paths():
    bridge = BRIDGE.read_text(encoding="utf-8")
    journal = JOURNAL.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    assert 'TZ_ReadLocalKV("updater_status.txt","last_action")' in bridge
    assert '"\\\"last_action\\\":\\\"%s\\\""' in bridge
    assert '"last_action": str(telemetry.get("last_action") or "")' in journal
    assert '"last_action": str(telemetry.get("last_action") or "")' in main
    assert '@app.get("/system/status")' in main


def test_runtime_not_falsely_declared_current_when_only_disk_is_installed():
    source = INSTALLER.read_text(encoding="utf-8")
    assert "if([string]$bridge.running -eq $ExpectedBridge -and [string]$seq.running -eq $ExpectedSequence)" in source
    assert "RUNTIME NOT YET CURRENT" in source
    assert "RUNTIME VERIFIED" in source
    assert "MT5 DISK INSTALL VERIFIED; CLOUD DASHBOARD ACKNOWLEDGEMENT IS STILL PENDING" in source
