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
