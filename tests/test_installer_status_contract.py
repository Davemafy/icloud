from pathlib import Path


def test_manual_installer_updates_mt5_version_truth_file():
    text = Path("mt5/installer/Install_TradeZone_MT5.ps1").read_text(encoding="utf-8")
    assert "updater_status.txt" in text
    assert "installed_bridge_version" in text
    assert "installed_sequence_version" in text
    assert "desired_bridge_version" in text
    assert "desired_sequence_version" in text
    assert "INSTALLED_REATTACH_REQUIRED" in text
    assert "Files\\TradeZone" in text or "Files\\\\TradeZone" in text
