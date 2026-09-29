from pathlib import Path


INSTALLER = Path("mt5/installer/Install_TradeZone_MT5.ps1")


def _text() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_installer_11_uses_unique_temp_compile_logs_not_experts_tree():
    text = _text()
    assert "$InstallerVersion='FRONT_FACING_MANUAL_INSTALLER_1.1'" in text
    assert "$compileLogDir=Join-Path $tmp 'compile_logs'" in text
    assert "[guid]::NewGuid().ToString('N')+'_compile.log'" in text
    compile_fn = text[text.index("function CompileOne"):text.index("function RemoveObsoleteManagedFiles")]
    assert "Join-Path $LogDir" in compile_fn
    assert "Join-Path $dest" not in compile_fn


def test_installer_waits_for_real_metaeditor_compile_summary():
    text = _text()
    compile_fn = text[text.index("function CompileOne"):text.index("function RemoveObsoleteManagedFiles")]
    assert "$deadline=(Get-Date).AddSeconds(20)" in compile_fn
    assert "$txt -match '\\d+ errors,\\s*\\d+ warnings'" in compile_fn
    assert "$txt -notmatch '0 errors,\\s*0 warnings'" in compile_fn
    assert "MetaEditor compile log was unavailable" in compile_fn


def test_installer_is_non_destructive_before_successful_compile():
    text = _text()
    backup_at = text.index("Existing TradeZone tree backed up before update.")
    compile_at = text.index("foreach($src in $srcs){CompileOne $meta $src $compileLogDir}")
    cleanup_at = text.index("RemoveObsoleteManagedFiles $dest $keepNames")
    assert backup_at < compile_at < cleanup_at

    pre_compile = text[backup_at:compile_at]
    assert "Get-ChildItem $dest -File" not in pre_compile


def test_locked_old_files_are_cleanup_warning_not_install_failure():
    text = _text()
    cleanup = text[text.index("function RemoveObsoleteManagedFiles"):text.index("function SaveManagedConfig")]
    assert "Remove-Item $_.FullName -Force -ErrorAction Stop" in cleanup
    assert 'Cleanup deferred (file in use)' in cleanup
    assert "catch{" in cleanup


def test_installer_keeps_only_current_ea_source_and_executable_names():
    text = _text()
    assert "$keepNames+=(Split-Path $src -Leaf)" in text
    assert "$keepNames+=([IO.Path]::GetFileName([IO.Path]::ChangeExtension($src,'.ex5')))" in text
    for pattern in (
        "InstitutionalSMC_DataBridge_*.mq5",
        "InstitutionalSMC_DataBridge_*.ex5",
        "InstitutionalSMC_SequenceEA_*.mq5",
        "InstitutionalSMC_SequenceEA_*.ex5",
        "*_compile.log",
    ):
        assert pattern in text
