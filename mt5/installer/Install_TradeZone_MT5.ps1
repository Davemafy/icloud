param([switch]$SkipCompile)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$InstallerVersion='FRONT_FACING_MANUAL_INSTALLER_1.4'
$Host.UI.RawUI.WindowTitle='Trade Zone - One-Click Demo MT5 Installer 1.4'

$Repo='Davemafy/icloud'
$Branch='main'
$ManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/stable/manifest.json"

function PauseExit([int]$Code=0){Write-Host '';Read-Host 'Press ENTER to close';exit $Code}
function Download([string]$Url,[string]$Out){
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 60
  if(!(Test-Path $Out)){throw "Download failed: $Url"}
  Unblock-File -LiteralPath $Out -ErrorAction SilentlyContinue
}
function Verify([string]$Path,[string]$Expected){
  if([string]::IsNullOrWhiteSpace($Expected)){throw "Missing SHA256 for $(Split-Path $Path -Leaf)"}
  $actual=(Get-FileHash -Algorithm SHA256 $Path).Hash.ToLowerInvariant()
  if($actual-ne([string]$Expected).ToLowerInvariant()){
    throw "SHA256 verification failed for $(Split-Path $Path -Leaf). Expected=$(([string]$Expected).ToLowerInvariant()) Actual=$actual. Nothing active was replaced."
  }
}
function FindMetaEditor($T){
  $c=@()
  if($T.Install){
    $b=$T.Install
    if(Test-Path $b -PathType Leaf){$b=Split-Path -Parent $b}
    $c+=Join-Path $b 'metaeditor64.exe'
    $c+=Join-Path $b 'MetaEditor64.exe'
    $c+=Join-Path $b 'metaeditor.exe'
  }
  foreach($r in @($env:ProgramFiles,${env:ProgramFiles(x86)})){
    if($r){
      $c+=Join-Path $r 'MetaTrader 5\metaeditor64.exe'
      $c+=Join-Path $r 'MetaTrader 5\MetaEditor64.exe'
      $c+=Join-Path $r 'MetaTrader 5\metaeditor.exe'
    }
  }
  foreach($p in $c){if($p-and(Test-Path $p)){return $p}}
  return $null
}
function PatchInput([string]$Path,[string]$Name,[string]$Value){
  $raw=Get-Content $Path -Raw
  $pattern='input\s+string\s+'+[regex]::Escape($Name)+'="[^"]*";'
  $replacement='input string '+$Name+'="'+$Value+'";'
  if($raw -notmatch $pattern){throw "Could not find $Name in $(Split-Path $Path -Leaf)"}
  $new=[regex]::Replace($raw,$pattern,$replacement,1)
  if($new-ne$raw){Set-Content $Path -Value $new -Encoding UTF8}
}
function PatchDefine([string]$Path,[string]$Name,[string]$Value){
  $raw=Get-Content $Path -Raw
  $pattern='#define\s+'+[regex]::Escape($Name)+'\s+"[^"]*"'
  $replacement='#define '+$Name+' "'+$Value+'"'
  if($raw -notmatch $pattern){throw "Could not find $Name in $(Split-Path $Path -Leaf)"}
  $new=[regex]::Replace($raw,$pattern,$replacement,1)
  if($new-ne$raw){Set-Content $Path -Value $new -Encoding UTF8}
}
function DiscoverTargets(){
  $root=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
  if(!(Test-Path $root)){throw 'MT5 terminal data root not found.'}
  $inst=@()
  Get-ChildItem $root -Directory|ForEach-Object{
    $mq=Join-Path $_.FullName 'MQL5'
    if(Test-Path $mq){
      $or=Join-Path $_.FullName 'origin.txt'
      $ip=$null
      if(Test-Path $or){try{$ip=(Get-Content $or -Raw).Trim()}catch{}}
      $inst+=[PSCustomObject]@{Data=$_.FullName;MQL5=$mq;Install=$ip}
    }
  }
  return @($inst)
}
function NormalizeMT5DataPath([string]$PathText){
  if([string]::IsNullOrWhiteSpace($PathText)){return ''}
  $p=$PathText.Trim().Trim('"').Trim("'")
  try{$p=[IO.Path]::GetFullPath($p)}catch{}
  return ($p -replace '[\\/]+$','').ToLowerInvariant()
}
function FindUniqueRunningMT5Target($targets){
  # Select automatically only if exactly one RUNNING MT5 executable matches
  # exactly one discovered MQL5 data-folder origin. Ignore unrelated MT4
  # terminal.exe processes; fail closed for two MT5s, portable or ambiguous paths.
  $running=@()
  try{
    $running=@(Get-CimInstance Win32_Process -Filter "Name = 'terminal64.exe' OR Name = 'terminal.exe'" -ErrorAction Stop)
  }catch{
    Write-Host 'Running MT5 detection unavailable; manual folder selection is required.' -ForegroundColor Yellow
    return $null
  }
  $matches=@()
  foreach($proc in @($running)){
    if([string]::IsNullOrWhiteSpace([string]$proc.ExecutablePath)){continue}
    if(([string]$proc.CommandLine) -match '(?i)(?:^|\s)[/-]portable(?:\s|$)'){continue}
    $liveInstall=NormalizeMT5DataPath (Split-Path -Parent ([string]$proc.ExecutablePath))
    if(!$liveInstall){continue}
    foreach($candidate in @($targets)){
      if([string]::IsNullOrWhiteSpace([string]$candidate.Install)){continue}
      $origin=[string]$candidate.Install
      if($origin -match '(?i)\\(?:terminal(?:64)?|metaeditor(?:64)?)\.exe$'){
        $origin=Split-Path -Parent $origin
      }
      if((NormalizeMT5DataPath $origin)-eq$liveInstall){
        $matches+=,[PSCustomObject]@{Target=$candidate;ProcessId=$proc.ProcessId}
      }
    }
  }
  if($matches.Count-ne1){return $null}
  return $matches[0].Target
}
function ChooseTarget($inst){
  $targets=@($inst)
  if($targets.Count-eq0){throw 'No MT5 data folder found.'}
  if($targets.Count-eq1){
    Write-Host "Only MT5 data folder: $($targets[0].Data)" -ForegroundColor White
    return $targets[0]
  }

  $liveTarget=FindUniqueRunningMT5Target $targets
  if($null-ne$liveTarget){
    Write-Host "AUTO-DETECTED RUNNING MT5 DATA FOLDER: $($liveTarget.Data)" -ForegroundColor Green
    Write-Host 'The only running MT5 terminal matches exactly one discovered data folder.' -ForegroundColor Green
    return $liveTarget
  }

  # Multiple, missing or ambiguous live terminals require an explicit choice.
  # Use the exact folder shown by the LIVE terminal's File > Open Data Folder.
  while($true){
    Write-Host ''
    Write-Host "DETECTED MT5 DATA FOLDERS ($($targets.Count)):" -ForegroundColor Yellow
    for($i=0;$i-lt$targets.Count;$i++){
      Write-Host ("  [{0}] DATA: {1}" -f ($i+1),[string]$targets[$i].Data) -ForegroundColor White
      if($targets[$i].Install){
        Write-Host ("      INSTALL: {0}" -f [string]$targets[$i].Install) -ForegroundColor Gray
      }
    }
    Write-Host 'In the MT5 terminal you use, click File > Open Data Folder.' -ForegroundColor Cyan
    Write-Host 'Paste that exact folder path below (safest), or enter its matching number.' -ForegroundColor Cyan
    $x=Read-Host 'MT5 data folder path or number'
    $choice=$null
    $n=0
    if([int]::TryParse($x,[ref]$n)){
      if($n-ge1-and$n-le$targets.Count){$choice=$targets[$n-1]}
    }else{
      $wanted=NormalizeMT5DataPath $x
      if($wanted){
        foreach($candidate in $targets){
          if((NormalizeMT5DataPath $candidate.Data)-eq$wanted){
            $choice=$candidate
            break
          }
        }
      }
    }
    if(!$choice){
      Write-Host 'Not a recognized MT5 data folder/number. No files changed. Try again.' -ForegroundColor Red
      continue
    }
    Write-Host "SELECTED MT5 DATA FOLDER: $($choice.Data)" -ForegroundColor Green
    $answer=(Read-Host 'Confirm this is the folder opened by your MT5 terminal? (Y/N)').Trim()
    if($answer -match '^(?i:y|yes)$'){return $choice}
    Write-Host 'Not confirmed. No files changed. Select again.' -ForegroundColor Yellow
  }
}
function BackupFile([string]$Path,[string]$BackupRoot,[string]$Name){
  if(Test-Path $Path){
    New-Item -ItemType Directory -Force -Path $BackupRoot|Out-Null
    Copy-Item $Path (Join-Path $BackupRoot $Name) -Force
  }
}
function CompileOne([string]$Meta,[string]$Src,[string]$LogDir){
  $name=[IO.Path]::GetFileNameWithoutExtension($Src)
  $ex5=[IO.Path]::ChangeExtension($Src,'.ex5')
  New-Item -ItemType Directory -Force -Path $LogDir|Out-Null

  # Never place MetaEditor logs inside the managed Experts\TradeZone folder.
  # A running/previous MetaEditor instance can keep those logs open briefly and
  # the old installer then failed before it even reached compilation. A unique
  # temp log makes compilation independent from stale/locked diagnostic files.
  $log=Join-Path $LogDir ($name+'_'+[guid]::NewGuid().ToString('N')+'_compile.log')

  # Remove only the executable we are about to rebuild. The compile log is new.
  Remove-Item $ex5 -Force -ErrorAction SilentlyContinue
  Write-Host "Compiling: $(Split-Path $Src -Leaf)" -ForegroundColor Cyan

  $p=Start-Process -FilePath $Meta -ArgumentList @("/compile:$Src","/log:$log") -PassThru
  $p.WaitForExit()

  # A running MetaEditor can delegate the command and release the launcher
  # process before compilation/log flushing has actually finished. Poll the
  # unique temp log for a real compile summary instead of racing the file handle.
  $txt=''
  $deadline=(Get-Date).AddSeconds(20)
  do{
    if(Test-Path $log){
      try{$txt=Get-Content $log -Raw -ErrorAction Stop}catch{$txt=''}
    }
    if((Test-Path $ex5) -and $txt -match '\d+ errors,\s*\d+ warnings'){break}
    Start-Sleep -Milliseconds 300
  }while((Get-Date)-lt$deadline)

  if(!(Test-Path $ex5)){
    if($txt){
      Write-Host ''
      Write-Host 'MetaEditor compile log:' -ForegroundColor Yellow
      Write-Host $txt -ForegroundColor DarkYellow
    }
    throw "Compilation failed for $(Split-Path $Src -Leaf)."
  }
  if([string]::IsNullOrWhiteSpace($txt)){
    throw "MetaEditor compile log was unavailable for $(Split-Path $Src -Leaf)."
  }
  if($txt -notmatch '0 errors,\s*0 warnings'){
    Write-Host ''
    Write-Host 'MetaEditor compile log:' -ForegroundColor Yellow
    Write-Host $txt -ForegroundColor DarkYellow
    throw "Compile did not report 0 errors, 0 warnings for $(Split-Path $Src -Leaf)."
  }
  Write-Host "  OK: 0 errors, 0 warnings." -ForegroundColor Green
}

function RemoveObsoleteManagedFiles([string]$Dest,[string[]]$KeepNames){
  if(!(Test-Path $Dest)){return}
  $keep=@{}
  foreach($n in @($KeepNames)){if($n){$keep[$n.ToLowerInvariant()]=$true}}

  # Cleanup is best-effort and happens only AFTER the new package has compiled.
  # A locked old log/EX5 must never make an otherwise valid install fail.
  Get-ChildItem $Dest -File -ErrorAction SilentlyContinue | ForEach-Object{
    $name=$_.Name
    $low=$name.ToLowerInvariant()
    $managed=(
      $name -like 'InstitutionalSMC_DataBridge_*.mq5' -or
      $name -like 'InstitutionalSMC_DataBridge_*.ex5' -or
      $name -like 'InstitutionalSMC_SequenceEA_*.mq5' -or
      $name -like 'InstitutionalSMC_SequenceEA_*.ex5' -or
      $name -like '*_compile.log'
    )
    if($managed -and !$keep.ContainsKey($low)){
      try{
        Remove-Item $_.FullName -Force -ErrorAction Stop
      }catch{
        Write-Host "  Cleanup deferred (file in use): $name" -ForegroundColor DarkYellow
      }
    }
  }
}
function SaveManagedConfig($T,[string]$CloudUrl,[string]$CloudKey){
  $root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
  New-Item -ItemType Directory -Force -Path $root|Out-Null
  $cfg=Join-Path $root 'config.json'
  $obj=[ordered]@{
    target_data_folder=$T.Data
    mt5_install_path=$T.Install
    cloud_url=$CloudUrl
    cloud_api_key=$CloudKey
    mode='MANUAL_ONLY'
    background_updater='DISABLED'
  }
  $obj|ConvertTo-Json -Depth 8|Set-Content $cfg -Encoding UTF8
}

Write-Host '================================================================' -ForegroundColor Cyan
Write-Host (" Trade Zone - ONE-CLICK DEMO MT5 INSTALLER 1.4") -ForegroundColor Cyan
Write-Host ' Current EA names + built-in demo cloud URL/key defaults' -ForegroundColor Cyan
Write-Host ' No background updater / no scheduled task' -ForegroundColor Yellow
Write-Host '================================================================' -ForegroundColor Cyan

$tmp=Join-Path $env:TEMP ('TradeZone_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp|Out-Null

try{
  $mf=Join-Path $tmp 'manifest.json'
  Write-Host 'Downloading stable manifest...' -ForegroundColor Cyan
  Download $ManifestUrl $mf
  $m=Get-Content $mf -Raw|ConvertFrom-Json
  if($m.schema-ne1-or!$m.files){throw 'Unsupported stable manifest.'}
  if($m.repository-ne$Repo){throw 'Manifest repository mismatch.'}
  if(!$m.demo_defaults){throw 'Stable manifest has no demo_defaults block.'}

  $cloudUrl=[string]$m.demo_defaults.cloud_base_url
  $cloudKey=[string]$m.demo_defaults.cloud_api_key
  if([string]::IsNullOrWhiteSpace($cloudUrl)-or[string]::IsNullOrWhiteSpace($cloudKey)){
    throw 'Demo cloud defaults are incomplete.'
  }

  Write-Host "Release $($m.release) | Bridge v$($m.data_bridge_version) | Sequence v$($m.sequence_ea_version)" -ForegroundColor Green
  Write-Host "Demo cloud URL: $cloudUrl" -ForegroundColor DarkCyan
  Write-Host "Demo API key : $cloudKey" -ForegroundColor DarkCyan

  # Download and verify ALL source/support files before touching the active MT5 tree.
  $fileDownloads=@()
  foreach($f in @($m.files)){
    $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
    $o=Join-Path $tmp ('file_'+$f.name)
    Write-Host "Downloading $($f.name)..." -ForegroundColor Cyan
    Download $u $o
    Verify $o ([string]$f.sha256)
    Write-Host '  SHA256 verified.' -ForegroundColor Green
    $fileDownloads+=[PSCustomObject]@{Def=$f;Path=$o}
  }

  $supportDownloads=@()
  foreach($f in @($m.support_files)){
    $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
    $o=Join-Path $tmp ('support_'+$f.name)
    Write-Host "Downloading support $($f.name)..." -ForegroundColor Cyan
    Download $u $o
    Verify $o ([string]$f.sha256)
    Write-Host '  SHA256 verified.' -ForegroundColor Green
    $supportDownloads+=[PSCustomObject]@{Def=$f;Path=$o}
  }

  # Inject demo defaults into the verified temporary support sources.
  foreach($x in $supportDownloads){
    if([string]$x.Def.role-eq'data_bridge_core'){
      PatchInput $x.Path 'CloudBaseUrl' $cloudUrl
      PatchInput $x.Path 'CloudApiKey' $cloudKey
      PatchInput $x.Path 'SequenceEaVersion' ([string]$m.sequence_ea_version)
    }
    if([string]$x.Def.role-eq'sequence_core'){
      PatchInput $x.Path 'CloudBaseUrl' $cloudUrl
      PatchInput $x.Path 'CloudApiKey' $cloudKey
    }
  }
  foreach($x in $fileDownloads){
    if([string]$x.Def.role-eq'data_bridge'){
      # Keep bridge heartbeat expectation aligned with the current Sequence runtime.
      try{PatchDefine $x.Path 'TZ_SEQUENCE_EXPECTED' ([string]$m.sequence_ea_version)}catch{
        Write-Host 'Bridge wrapper has no TZ_SEQUENCE_EXPECTED patch point; continuing.' -ForegroundColor DarkYellow
      }
    }
  }

  $inst=DiscoverTargets
  $t=ChooseTarget $inst
  Write-Host "MT5 data folder: $($t.Data)" -ForegroundColor Green

  $meta=FindMetaEditor $t
  if(!$SkipCompile-and!$meta){throw 'MetaEditor not found.'}

  $dest=Join-Path $t.MQL5 'Experts\TradeZone'
  $backupRoot=Join-Path $env:LOCALAPPDATA ('TradeZoneMT5\backups\installer_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
  $includeBackup=Join-Path $backupRoot 'include'
  $expertsBackup=Join-Path $backupRoot 'experts'
  New-Item -ItemType Directory -Force -Path $includeBackup,$expertsBackup|Out-Null

  # Back up the complete TradeZone tree. Do NOT destructively clean the live
  # directory before the replacement package has compiled successfully.
  if(Test-Path $dest){
    Copy-Item $dest (Join-Path $expertsBackup 'TradeZone') -Recurse -Force
    Write-Host 'Existing TradeZone tree backed up before update.' -ForegroundColor DarkCyan
  }else{
    New-Item -ItemType Directory -Force -Path $dest|Out-Null
  }

  # Install patched support sources.
  foreach($x in $supportDownloads){
    $targetRoot=Join-Path $t.MQL5 ([string]$x.Def.target)
    New-Item -ItemType Directory -Force -Path $targetRoot|Out-Null
    $target=Join-Path $targetRoot ([string]$x.Def.target_name)
    BackupFile $target $includeBackup ([string]$x.Def.target_name)
    Copy-Item $x.Path $target -Force
  }

  # Install only the current front-facing EA sources.
  $srcs=@()
  foreach($x in $fileDownloads){
    $name=[string]$x.Def.target_name
    if([string]::IsNullOrWhiteSpace($name)){$name=[string]$x.Def.name}
    $d=Join-Path $dest $name
    Copy-Item $x.Path $d -Force
    $srcs+=$d
  }

  if(!$SkipCompile){
    $compileLogDir=Join-Path $tmp 'compile_logs'
    foreach($src in $srcs){CompileOne $meta $src $compileLogDir}
  }

  # New sources/executables are now in place. Prune only obsolete managed
  # front-facing files, and never fail the install if an old diagnostic/ex5 is
  # temporarily locked by MT5/MetaEditor.
  $keepNames=@()
  foreach($src in $srcs){
    $keepNames+=(Split-Path $src -Leaf)
    $keepNames+=([IO.Path]::GetFileName([IO.Path]::ChangeExtension($src,'.ex5')))
  }
  RemoveObsoleteManagedFiles $dest $keepNames

  # Publish disk-install truth only after every download is verified and every
  # front-facing EA has compiled successfully. DataBridge reads this exact file.
  $statusDir=Join-Path $t.MQL5 'Files\TradeZone'
  New-Item -ItemType Directory -Force -Path $statusDir|Out-Null
  $statusFile=Join-Path $statusDir 'updater_status.txt'
  $statusLines=@(
    'updater_version='+$InstallerVersion,
    'stable_release='+[string]$m.release,
    'desired_bridge_version='+[string]$m.data_bridge_version,
    'desired_sequence_version='+[string]$m.sequence_ea_version,
    'installed_bridge_version='+[string]$m.data_bridge_version,
    'installed_sequence_version='+[string]$m.sequence_ea_version,
    'pending_reload=1',
    'result=INSTALLED_REATTACH_REQUIRED',
    'update_result=INSTALLED_REATTACH_REQUIRED',
    'last_action=MANUAL_INSTALL_COMPILED'
  )
  $statusTmp=$statusFile+'.tmp'
  [IO.File]::WriteAllLines($statusTmp,[string[]]$statusLines,(New-Object System.Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $statusTmp -Destination $statusFile -Force
  Write-Host "Disk version truth written to: $statusFile" -ForegroundColor Green

  SaveManagedConfig $t $cloudUrl $cloudKey

  Write-Host ''
  Write-Host 'SUCCESS: CURRENT TRADE ZONE EAs INSTALLED.' -ForegroundColor Green
  Write-Host "  Installer $InstallerVersion" -ForegroundColor Green
  Write-Host "  DataBridge v$($m.data_bridge_version)" -ForegroundColor Green
  Write-Host "  Sequence EA v$($m.sequence_ea_version)" -ForegroundColor Green
  Write-Host "  Cloud URL/key are already the EA defaults." -ForegroundColor Green
  Write-Host "  Old TradeZone Navigator tree backed up to: $expertsBackup" -ForegroundColor DarkGray
  Write-Host '  Existing TradeZone subfolders were preserved.' -ForegroundColor DarkGray
  Write-Host ''
  Write-Host 'MT5: Navigator > Expert Advisors > right-click Refresh > TradeZone.' -ForegroundColor Cyan
  Write-Host 'Attach DataBridge once to XAUUSD; attach Sequence EA to XAUUSD M1.' -ForegroundColor Cyan
  Write-Host 'Add the Railway URL once under Tools > Options > Expert Advisors > Allow WebRequest.' -ForegroundColor Yellow
  Write-Host 'Keep DEMO/PAPER_ONLY while validating.' -ForegroundColor Yellow
  PauseExit 0
}
catch{
  Write-Host ''
  Write-Host "INSTALLER FAILED: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host 'Downloaded files failed closed. Review the message before retrying.' -ForegroundColor Yellow
  PauseExit 1
}
finally{
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
