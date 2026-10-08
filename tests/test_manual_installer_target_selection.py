"""Regression checks for fail-closed multi-MT5 installer target selection."""
from pathlib import Path

INSTALLER = Path("mt5/installer/Install_TradeZone_MT5.ps1")


def _chooser() -> str:
    source = INSTALLER.read_text(encoding="utf-8")
    return source.split("function ChooseTarget($inst){", 1)[1].split("function BackupFile(", 1)[0]


def test_multiple_mt5_folders_are_shown_with_visible_number_and_data_path():
    chooser = _chooser()
    assert 'DETECTED MT5 DATA FOLDERS' in chooser
    assert 'DATA: {1}' in chooser
    assert '-ForegroundColor White' in chooser
    assert '$targets[$i].Data' in chooser


def test_exact_live_mt5_data_folder_can_be_pasted_instead_of_guessing():
    chooser = _chooser()
    assert 'MT5 data folder path or number' in chooser
    assert 'NormalizeMT5DataPath $x' in chooser
    assert 'NormalizeMT5DataPath $candidate.Data' in chooser
    assert '$targets[$n-1]' in chooser


def test_multiple_terminal_selection_is_fail_closed_until_confirmed():
    chooser = _chooser()
    assert 'if(!$choice)' in chooser
    assert 'No files changed' in chooser
    assert 'Confirm this is the folder opened by your MT5 terminal?' in chooser
    assert "if($answer -match '^(?i:y|yes)$'){return $choice}" in chooser
    assert 'Select again' in chooser


def test_only_one_running_terminal_can_be_auto_selected():
    source = INSTALLER.read_text(encoding="utf-8")
    helper = source.split("function FindUniqueRunningMT5Target($targets){", 1)[1].split("function ChooseTarget($inst){", 1)[0]
    assert "Get-CimInstance Win32_Process" in helper
    assert "terminal64.exe" in helper
    assert "terminal.exe" in helper
    assert "if($running.Count-ne1){return $null}" in helper
    assert "if($matches.Count-ne1){return $null}" in helper
    assert "NormalizeMT5DataPath $origin" in helper
    assert "NormalizeMT5DataPath (Split-Path -Parent" in helper
    assert "portable" in helper


def test_automatic_detection_precedes_manual_picker_without_unsafe_default():
    chooser = _chooser()
    assert "$liveTarget=FindUniqueRunningMT5Target $targets" in chooser
    assert "if($null-ne$liveTarget)" in chooser
    assert "AUTO-DETECTED RUNNING MT5 DATA FOLDER" in chooser
    assert chooser.index("FindUniqueRunningMT5Target $targets") < chooser.index("while($true)")
    assert "Read-Host 'MT5 data folder path or number'" in chooser
