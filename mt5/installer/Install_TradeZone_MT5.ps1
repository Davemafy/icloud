param([switch]$SkipCompile)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle = 'Trade Zone - ONE GitHub MT5 Installer + Background Updater'

$Repo = 'Davemafy/icloud'
$Branch = 'main'
$BaseRaw = "https://raw.githubusercontent.com/$Repo/$Branch"
$ManifestUrl = "$BaseRaw/mt5/stable/manifest.json"
$UpdaterUrl = "$BaseRaw/mt5/installer/TradeZone_MT5_Updater.ps1"
$AppDir = Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
$StatePath = Join-Path $AppDir 'state.json'
$UpdaterLocal = Join-Path $AppDir 'TradeZone_MT5_Updater.ps1'
$LogPath = Join-Path $AppDir 'installer.log'
$TaskName = 'TradeZone MT5 Background Updater'

function Log([string]$Text) {
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Text"
    $line | Tee-Object -FilePath $LogPath -Append | Write-Host
}
function PauseExit([int]$Code = 0) {
    Write-Host ''
    Read-Host 'Press ENTER to close'
    exit $Code
}
function Download([string]$Url, [string]$Out) {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 60
    if (!(Test-Path $Out)) { throw "Download failed: $Url" }
}
function Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}
function FindMetaEditor([string]$TerminalRoot) {
    $candidates = @()
    $origin = Join-Path $TerminalRoot 'origin.txt'
    if (Test-Path $origin) {
        $install = (Get-Content $origin -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($install) {
            if (Test-Path $install -PathType Leaf) { $install = Split-Path -Parent $install }
            $candidates += (Join-Path $install 'metaeditor64.exe')
            $candidates += (Join-Path $install 'MetaEditor64.exe')
            $candidates += (Join-Path $install 'metaeditor.exe')
        }
    }
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($root) {
            $candidates += (Join-Path $root 'MetaTrader 5\metaeditor64.exe')
            $candidates += (Join-Path $root 'MetaTrader 5\MetaEditor64.exe')
            $candidates += (Join-Path $root 'MetaTrader 5\metaeditor.exe')
        }
    }
    foreach ($p in ($candidates | Select-Object -Unique)) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    return $null
}
function CompileEA([string]$MetaEditor, [string]$Mq5, [string]$LogFile) {
    if (!(Test-Path $MetaEditor)) { throw "MetaEditor not found: $MetaEditor" }
    if (Test-Path $LogFile) { Remove-Item $LogFile -Force -ErrorAction SilentlyContinue }
    $args = @("/compile:`"$Mq5`"", "/log:`"$LogFile`"")
    $p = Start-Process -FilePath $MetaEditor -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 400
    $ex5 = [IO.Path]::ChangeExtension($Mq5, '.ex5')
    $logText = if (Test-Path $LogFile) { Get-Content $LogFile -Raw -ErrorAction SilentlyContinue } else { '' }
    if (!(Test-Path $ex5)) {
        throw "Compilation did not create $([IO.Path]::GetFileName($ex5)).`n$logText"
    }
    if ($logText -match '(?im)^\s*[1-9]\d*\s+errors?\b' -or $logText -match '(?im)\berror\s+[A-Z0-9]+\b') {
        throw "MetaEditor reported a compile error for $([IO.Path]::GetFileName($Mq5)).`n$logText"
    }
    return $ex5
}
function InstallBackgroundTask([string]$UpdaterScript) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$UpdaterScript`" -Mode Background"
    $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(10)) -RepetitionInterval (New-TimeSpan -Hours 1)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Checks Davemafy/icloud for approved TradeZone EA updates and stages/installs them safely.' -Force | Out-Null
        return $true
    } catch {
        Log "ScheduledTasks cmdlets failed: $($_.Exception.Message)"
        $taskCommand = "powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$UpdaterScript`" -Mode Background"
        $args = @('/Create','/F','/TN',$TaskName,'/SC','HOURLY','/MO','1','/TR',$taskCommand)
        $proc = Start-Process -FilePath 'schtasks.exe' -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
        return ($proc.ExitCode -eq 0)
    }
}

Write-Host '==================================================================' -ForegroundColor Cyan
Write-Host ' Trade Zone - ONE MT5 Installer + Background Update Watcher' -ForegroundColor Cyan
Write-Host ' GitHub -> SHA256 -> archive -> install -> compile -> watch hourly' -ForegroundColor Cyan
Write-Host '==================================================================' -ForegroundColor Cyan
Write-Host ''

New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
$tmp = Join-Path $env:TEMP ('TradeZone_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

try {
    Log 'Starting installer.'
    $manifestPath = Join-Path $tmp 'manifest.json'
    Download $ManifestUrl $manifestPath
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    Log "Approved release: $($manifest.release); Sequence EA: $($manifest.sequence_ea_version); DataBridge: $($manifest.data_bridge_version)"

    $terminalRoots = @()
    $base = Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    if (Test-Path $base) {
        Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $mql5 = Join-Path $_.FullName 'MQL5'
            if ((Test-Path $mql5) -and (Test-Path (Join-Path $_.FullName 'origin.txt'))) {
                $terminalRoots += $_.FullName
            }
        }
    }
    if ($terminalRoots.Count -eq 0) {
        throw 'No MT5 data folder found under %APPDATA%\MetaQuotes\Terminal. Start MT5 once, then run this installer again.'
    }

    if ($terminalRoots.Count -eq 1) {
        $terminalRoot = $terminalRoots[0]
    } else {
        Write-Host 'Multiple MT5 terminals were found:' -ForegroundColor Yellow
        for ($i = 0; $i -lt $terminalRoots.Count; $i++) {
            $origin = Join-Path $terminalRoots[$i] 'origin.txt'
            $originText = (Get-Content $origin -ErrorAction SilentlyContinue | Select-Object -First 1)
            Write-Host " [$($i+1)] $($terminalRoots[$i])"
            if ($originText) { Write-Host "     $originText" -ForegroundColor DarkGray }
        }
        do {
            $pick = Read-Host "Choose MT5 terminal [1-$($terminalRoots.Count)]"
            $n = 0
            [void][int]::TryParse($pick, [ref]$n)
        } while ($n -lt 1 -or $n -gt $terminalRoots.Count)
        $terminalRoot = $terminalRoots[$n-1]
    }

    $mql5 = Join-Path $terminalRoot 'MQL5'
    $target = Join-Path $mql5 'Experts\TradeZone'
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Log "Selected MT5 data folder: $terminalRoot"

    $downloaded = @()
    foreach ($f in $manifest.files) {
        $out = Join-Path $tmp $f.name
        $url = "$BaseRaw/$($f.path)"
        Log "Downloading $($f.name)"
        Download $url $out
        $actual = Sha256 $out
        if ($actual -ne $f.sha256.ToLowerInvariant()) {
            throw "SHA256 verification failed for $($f.name). Expected $($f.sha256), got $actual"
        }
        $downloaded += [pscustomobject]@{ Role=$f.role; Name=$f.name; Path=$out; Sha256=$actual }
    }
    Log 'All GitHub EA files passed SHA256 verification.'

    $archive = Join-Path $target ('_archive\' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
    $existing = @(Get-ChildItem $target -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'InstitutionalSMC_*' -and ($_.Extension -in '.mq5','.ex5') })
    if ($existing.Count -gt 0) {
        New-Item -ItemType Directory -Force -Path $archive | Out-Null
        foreach ($old in $existing) { Move-Item $old.FullName (Join-Path $archive $old.Name) -Force }
        Log "Archived $($existing.Count) existing TradeZone EA file(s) to $archive"
    }

    foreach ($f in $downloaded) { Copy-Item $f.Path (Join-Path $target $f.Name) -Force }
    Log 'Approved MQ5 sources installed.'

    $meta = FindMetaEditor $terminalRoot
    if (-not $SkipCompile) {
        if (-not $meta) { throw 'MetaEditor was not found automatically. The source files were installed, but automatic compilation cannot continue.' }
        Log "MetaEditor: $meta"
        foreach ($f in $downloaded) {
            $mq5 = Join-Path $target $f.Name
            $compileLog = Join-Path $AppDir ($f.Name + '.compile.log')
            [void](CompileEA $meta $mq5 $compileLog)
            Log "Compiled successfully: $($f.Name)"
        }
    } else {
        Log 'Compilation skipped by -SkipCompile.'
    }

    $installedManifest = Join-Path $target 'installed_manifest.json'
    Copy-Item $manifestPath $installedManifest -Force

    $state = [ordered]@{
        schema = 2
        repository = $Repo
        branch = $Branch
        terminal_root = $terminalRoot
        mql5_path = $mql5
        target_dir = $target
        metaeditor = $meta
        installed_release = [string]$manifest.release
        installed_at = (Get-Date).ToString('o')
        updater_task = $TaskName
        paper_only = $true
    }
    $state | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $StatePath
    Log "Saved updater state: $StatePath"

    Download $UpdaterUrl $UpdaterLocal
    Log "Installed background updater: $UpdaterLocal"
    $taskOk = InstallBackgroundTask $UpdaterLocal
    if ($taskOk) {
        Log "Background update task installed: $TaskName (checks hourly)."
    } else {
        Log 'WARNING: EA installation succeeded, but Windows background task creation failed.'
    }

    Write-Host ''
    Write-Host 'SUCCESS: TRADE ZONE IS INSTALLED.' -ForegroundColor Green
    if (-not $SkipCompile) { Write-Host 'Both approved EAs were downloaded, verified and compiled.' -ForegroundColor Green }
    if ($taskOk) {
        Write-Host 'Background updater: ENABLED (hourly).' -ForegroundColor Green
        Write-Host 'If MT5 is running when an update arrives, the update is staged and waits until MT5 is closed.' -ForegroundColor Yellow
    } else {
        Write-Host 'Background updater: NOT INSTALLED. Re-run as Administrator if you want the hourly task.' -ForegroundColor Yellow
    }
    Write-Host ''
    Write-Host 'MT5 one-time permissions still required:' -ForegroundColor Cyan
    Write-Host '  1. Enable Algo Trading.'
    Write-Host '  2. Add your Railway HTTPS URL under Tools > Options > Expert Advisors > Allow WebRequest.'
    Write-Host '  3. Refresh Navigator / restart MT5, then use the TradeZone EAs on DEMO/PAPER_ONLY.'
    Write-Host ''
    Write-Host "Updater log: $LogPath"
    Write-Host "Updater state: $StatePath"
    PauseExit 0
}
catch {
    Log "ERROR: $($_.Exception.Message)"
    Write-Host ''
    Write-Host 'INSTALLATION FAILED' -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Log: $LogPath"
    PauseExit 1
}
finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
