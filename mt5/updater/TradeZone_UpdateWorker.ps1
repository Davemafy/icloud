param(
  [switch]$Interactive,
  [switch]$Force
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

$UpdaterVersion='2.6.0'
$Repo='Davemafy/icloud'
$Branch='main'
$Root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
$Bin=Join-Path $Root 'bin'
$StageRoot=Join-Path $Root 'staging'
$Log=Join-Path $Root 'updater.log'
$StatePath=Join-Path $Root 'state.json'
$StatusPath=Join-Path $Root 'status.json'
$ConfigPath=Join-Path $Root 'config.json'
$StableManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/stable/manifest.json"
$UpdaterManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/updater/manifest.json"
$BootstrapPath=Join-Path $Bin 'TradeZone_UpdateBootstrap.ps1'
$script:SafeSince=$null

New-Item -ItemType Directory -Force -Path $Root,$Bin,$StageRoot | Out-Null

function Log([string]$Message,[string]$Level='INFO'){
  $line="$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Message"
  Add-Content -Path $Log -Value $line -Encoding UTF8
  if($Interactive){
    $c=if($Level-eq'ERROR'){'Red'}elseif($Level-eq'WARN'){'Yellow'}elseif($Level-eq'OK'){'Green'}else{'Cyan'}
    Write-Host $line -ForegroundColor $c
  }
}
function Load-Json([string]$Path){
  if(Test-Path $Path){try{return (Get-Content $Path -Raw|ConvertFrom-Json)}catch{}}
  return $null
}
function Save-Json($Object,[string]$Path){
  $Object|ConvertTo-Json -Depth 10|Set-Content -Path $Path -Encoding UTF8
}
function Download([string]$Url,[string]$Out){
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 45
  if(!(Test-Path $Out)){throw "Download failed: $Url"}
}
function Verify([string]$Path,[string]$Expected){
  $actual=(Get-FileHash -Algorithm SHA256 $Path).Hash.ToLowerInvariant()
  if($actual-ne([string]$Expected).ToLowerInvariant()){
    throw "SHA256 verification failed for $(Split-Path $Path -Leaf)"
  }
}
function Read-KVFile([string]$Path){
  $o=[ordered]@{}
  if(!(Test-Path $Path)){return [pscustomobject]$o}
  foreach($line in Get-Content $Path -ErrorAction SilentlyContinue){
    $i=$line.IndexOf('=')
    if($i -gt 0){$o[$line.Substring(0,$i)]=$line.Substring($i+1)}
  }
  return [pscustomobject]$o
}
function EpochNow(){return [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}
function Normalize-PathText([string]$PathText){
  if([string]::IsNullOrWhiteSpace($PathText)){return $null}
  $x=$PathText.Trim().Trim('"')
  try{$x=[IO.Path]::GetFullPath($x)}catch{}
  if($x.ToLowerInvariant().EndsWith('.exe')){$x=Split-Path -Parent $x}
  return $x.TrimEnd('\').ToLowerInvariant()
}
function Get-ManagedTerminalProcess($cfg){
  $expected=Normalize-PathText ([string]$cfg.mt5_install_path)
  $rows=@()
  try{
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object{$_.Name -match '^(terminal|terminal64)\.exe$'} |
      ForEach-Object{
        $exe=[string]$_.ExecutablePath
        if($exe){
          $rows += [pscustomobject]@{Pid=[int]$_.ProcessId;Exe=$exe;Dir=(Normalize-PathText (Split-Path -Parent $exe))}
        }
      }
  }catch{}
  if($expected){
    $match=@($rows|Where-Object{$_.Dir -eq $expected})
    if($match.Count -eq 1){return $match[0]}
  }
  if($rows.Count -eq 1){return $rows[0]}
  return $null
}
function MT5-Running($cfg){
  if(Get-ManagedTerminalProcess $cfg){return $true}
  try{
    if(Get-Process -ErrorAction SilentlyContinue|Where-Object{$_.ProcessName -match '^(terminal|terminal64)$'}){return $true}
  }catch{}
  return $false
}
function Find-MetaEditor($cfg){
  $c=@()
  if($cfg -and $cfg.mt5_install_path){
    $b=[string]$cfg.mt5_install_path
    if(Test-Path $b -PathType Leaf){$b=Split-Path -Parent $b}
    $c+=Join-Path $b 'metaeditor64.exe'
    $c+=Join-Path $b 'MetaEditor64.exe'
    $c+=Join-Path $b 'metaeditor.exe'
  }
  foreach($r in @($env:ProgramFiles,${env:ProgramFiles(x86)})){
    if($r){
      $c+=Join-Path $r 'MetaTrader 5\metaeditor64.exe'
      $c+=Join-Path $r 'MetaTrader 5\MetaEditor64.exe'
    }
  }
  foreach($p in $c){if($p -and (Test-Path $p)){return $p}}
  return $null
}
function Archive-One([string]$Path,[string]$ArchiveDir){
  if(Test-Path $Path){
    New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
    Copy-Item $Path (Join-Path $ArchiveDir (Split-Path $Path -Leaf)) -Force
  }
}
function Target-IsCurrent($item,[string]$mql5){
  $dest=Join-Path (Join-Path $mql5 $item.Target) $item.TargetName
  if(!(Test-Path $dest)){return $false}
  try{
    $h=(Get-FileHash -Algorithm SHA256 $dest).Hash.ToLowerInvariant()
    if($h-ne $item.Sha.ToLowerInvariant()){return $false}
  }catch{return $false}
  if($item.Role -ne 'support' -and $item.TargetName.ToLowerInvariant().EndsWith('.mq5')){
    if(!(Test-Path ([IO.Path]::ChangeExtension($dest,'.ex5')))){return $false}
  }
  return $true
}
function Build-Items($m,[string]$stage){
  $items=@()
  # Support/core dependencies first so wrapper EAs can compile against them.
  if($m.support_files){
    foreach($f in $m.support_files){
      $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
      $o=Join-Path $stage $f.name
      Download $u $o;Verify $o $f.sha256
      $targetName=if($f.target_name){[string]$f.target_name}else{[string]$f.name}
      $items += [pscustomobject]@{
        Role='support';SourceName=[string]$f.name;TargetName=$targetName;DownloadPath=$o;Sha=[string]$f.sha256
        Target=[string]$f.target;RequiresReload=$false
      }
    }
  }
  foreach($f in $m.files){
    $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
    $o=Join-Path $stage $f.name
    Download $u $o;Verify $o $f.sha256
    $targetName=if($f.target_name){[string]$f.target_name}else{[string]$f.name}
    $reload=$true
    if($null-ne $f.requires_reload){$reload=[bool]$f.requires_reload}
    $items += [pscustomobject]@{
      Role=[string]$f.role;SourceName=[string]$f.name;TargetName=$targetName;DownloadPath=$o;Sha=[string]$f.sha256
      Target='Experts\TradeZone';RequiresReload=$reload
    }
  }
  return @($items)
}
function Install-Item($item,[string]$mql5,$cfg,[string]$release){
  if(Target-IsCurrent $item $mql5){return 'CURRENT'}
  $destDir=Join-Path $mql5 $item.Target
  New-Item -ItemType Directory -Force -Path $destDir|Out-Null

  if($item.Role -eq 'support'){
    $dest=Join-Path $destDir $item.TargetName
    $archive=Join-Path (Join-Path $mql5 'Experts\TradeZone\_archive') (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
    Archive-One $dest $archive
    Copy-Item $item.DownloadPath $dest -Force
    return 'UPDATED'
  }

  if($item.TargetName.ToLowerInvariant().EndsWith('.mq5')){
    $compileDir=Join-Path (Join-Path $mql5 'Experts\TradeZone\_staging') $release
    New-Item -ItemType Directory -Force -Path $compileDir|Out-Null
    $src=Join-Path $compileDir $item.SourceName
    Copy-Item $item.DownloadPath $src -Force

    $me=Find-MetaEditor $cfg
    if(!$me){throw "MetaEditor not found. Verified source remains staged: $($item.SourceName)"}
    $ex5=[IO.Path]::ChangeExtension($src,'.ex5')
    $clog=Join-Path $compileDir (([IO.Path]::GetFileNameWithoutExtension($src))+'_compile.log')
    Log "Compiling $($item.SourceName)"
    Start-Process -FilePath $me -ArgumentList @("/compile:$src","/log:$clog") -Wait|Out-Null
    Start-Sleep -Milliseconds 700
    if(!(Test-Path $ex5)){
      $tail=''
      if(Test-Path $clog){$tail=(Get-Content $clog -Tail 14)-join' | '}
      throw "Compile failed for $($item.SourceName). Existing EA was left unchanged. $tail"
    }

    $destMq5=Join-Path $destDir $item.TargetName
    $destEx5=[IO.Path]::ChangeExtension($destMq5,'.ex5')
    $archive=Join-Path (Join-Path $mql5 'Experts\TradeZone\_archive') (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
    Archive-One $destMq5 $archive
    Archive-One $destEx5 $archive
    Copy-Item $src $destMq5 -Force
    Copy-Item $ex5 $destEx5 -Force
    return 'UPDATED'
  }

  $dest=Join-Path $destDir $item.TargetName
  $archive=Join-Path (Join-Path $mql5 'Experts\TradeZone\_archive') (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
  Archive-One $dest $archive
  Copy-Item $item.DownloadPath $dest -Force
  return 'UPDATED'
}
function Read-RuntimeState([string]$mql5,[string]$name){
  $p=Join-Path $mql5 ("Files\TradeZone\"+$name)
  $x=Read-KVFile $p
  $age=$null
  if($x.ts){
    try{$age=(EpochNow)-[int]$x.ts}catch{}
  }
  return [pscustomobject]@{Path=$p;Data=$x;Age=$age}
}
function Write-LocalUpdaterStatus([string]$mql5,$m,[string]$result,[string]$lastAction,[bool]$pendingReload){
  $dir=Join-Path $mql5 'Files\TradeZone'
  New-Item -ItemType Directory -Force -Path $dir|Out-Null
  $bridgeItem=$null;$seqItem=$null
  foreach($f in $m.files){
    if([string]$f.role -eq 'data_bridge'){$bridgeItem=$f}
    if([string]$f.role -eq 'sequence_ea'){$seqItem=$f}
  }
  $bridgeInstalled=''
  $seqInstalled=''
  if($bridgeItem){
    $target=if($bridgeItem.target_name){[string]$bridgeItem.target_name}else{[string]$bridgeItem.name}
    $p=Join-Path (Join-Path $mql5 'Experts\TradeZone') $target
    if(Test-Path $p){
      try{if((Get-FileHash -Algorithm SHA256 $p).Hash.ToLowerInvariant()-eq([string]$bridgeItem.sha256).ToLowerInvariant()){$bridgeInstalled=[string]$m.data_bridge_version}}catch{}
    }
  }
  if($seqItem){
    $target=if($seqItem.target_name){[string]$seqItem.target_name}else{[string]$seqItem.name}
    $p=Join-Path (Join-Path $mql5 'Experts\TradeZone') $target
    if(Test-Path $p){
      try{if((Get-FileHash -Algorithm SHA256 $p).Hash.ToLowerInvariant()-eq([string]$seqItem.sha256).ToLowerInvariant()){$seqInstalled=[string]$m.sequence_ea_version}}catch{}
    }
  }
  $lines=@(
    "ts=$(EpochNow)",
    "updater_version=$UpdaterVersion",
    "stable_release=$($m.release)",
    "desired_bridge_version=$($m.data_bridge_version)",
    "desired_sequence_version=$($m.sequence_ea_version)",
    "installed_bridge_version=$bridgeInstalled",
    "installed_sequence_version=$seqInstalled",
    "pending_reload="+($(if($pendingReload){'1'}else{'0'})),
    "result=$result",
    "last_action=$lastAction"
  )
  Set-Content -Path (Join-Path $dir 'updater_status.txt') -Value $lines -Encoding ASCII
  return [pscustomobject]@{Bridge=$bridgeInstalled;Sequence=$seqInstalled}
}
function Write-StatusJson($cfg,$m,[string]$result,[string]$message,$installed,[bool]$pendingReload,$seqState,$bridgeState){
  $cloud='UNKNOWN';$cloudVer=$null
  if($cfg -and $cfg.cloud_url){
    try{
      $h=Invoke-RestMethod -Uri (($cfg.cloud_url.TrimEnd('/'))+'/health') -TimeoutSec 8
      if($h.ok){$cloud='ONLINE'}else{$cloud='DEGRADED'}
      if($h.version){$cloudVer=[string]$h.version}
    }catch{$cloud='UNREACHABLE'}
  }
  Save-Json ([ordered]@{
    checked_at=(Get-Date).ToString('o');result=$result;message=$message;updater_version=$UpdaterVersion
    target_data_folder=$cfg.target_data_folder
    stable_release=if($m){[string]$m.release}else{$null}
    desired_bridge_version=if($m){[string]$m.data_bridge_version}else{$null}
    desired_sequence_version=if($m){[string]$m.sequence_ea_version}else{$null}
    installed_bridge_version=if($installed){$installed.Bridge}else{$null}
    installed_sequence_version=if($installed){$installed.Sequence}else{$null}
    running_bridge_version=if($bridgeState){$bridgeState.Data.version}else{$null}
    running_sequence_version=if($seqState){$seqState.Data.version}else{$null}
    restart_safe=if($seqState){$seqState.Data.restart_safe}else{$null}
    pending_reload=$pendingReload
    cloud_status=$cloud;cloud_version=$cloudVer
  }) $StatusPath
}
function Try-SafeRestart($cfg,[string]$mql5,[bool]$pendingReload,$seqState){
  if(!$pendingReload){$script:SafeSince=$null;return $false}
  if(!$seqState -or $seqState.Age -eq $null -or $seqState.Age -gt 30 -or [string]$seqState.Data.restart_safe -ne '1'){
    $script:SafeSince=$null;return $false
  }
  if(!$script:SafeSince){$script:SafeSince=Get-Date;Log 'Safe-restart gate is GREEN; waiting 20 seconds for a stable idle state.' 'INFO';return $false}
  if(((Get-Date)-$script:SafeSince).TotalSeconds -lt 20){return $false}

  $managed=Get-ManagedTerminalProcess $cfg
  if(!$managed){Log 'Update is installed but automatic reload cannot identify exactly one managed MT5 process. Leaving RESTART REQUIRED.' 'WARN';return $false}
  try{$p=Get-Process -Id $managed.Pid -ErrorAction Stop}catch{return $false}
  Log "Safe idle state confirmed. Requesting graceful MT5 reload for PID $($managed.Pid)." 'OK'
  $exe=$managed.Exe
  $closed=$false
  try{$closed=$p.CloseMainWindow()}catch{}
  if(!$closed){Log 'MT5 did not accept a graceful close request. No force-kill will be used.' 'WARN';return $false}
  try{Wait-Process -Id $managed.Pid -Timeout 20 -ErrorAction Stop}catch{
    Log 'MT5 did not close within 20 seconds. No force-kill will be used; reload remains pending.' 'WARN'
    return $false
  }
  Start-Sleep -Seconds 2
  try{
    Start-Process -FilePath $exe | Out-Null
    Log 'MT5 restarted automatically after a safe idle gate. Attached charts should reload the newly installed EA files.' 'OK'
    $script:SafeSince=$null
    return $true
  }catch{
    Log "MT5 closed safely but automatic relaunch failed: $($_.Exception.Message)" 'ERROR'
    return $false
  }
}
function Updater-Superseded(){
  try{
    $u=Invoke-RestMethod -Uri $UpdaterManifestUrl -TimeoutSec 15
    return ([string]$u.updater_version -ne $UpdaterVersion)
  }catch{return $false}
}

function Update-Once(){
  $cfg=Load-Json $ConfigPath
  if(!$cfg -or !$cfg.target_data_folder){Log 'Updater is not configured.' 'ERROR';return 10}
  $mql5=Join-Path ([string]$cfg.target_data_folder) 'MQL5'
  if(!(Test-Path $mql5)){Log "Configured MQL5 folder missing: $mql5" 'ERROR';return 11}

  $tmp=Join-Path $env:TEMP ('TradeZoneUpdate_'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tmp|Out-Null
  try{
    $mf=Join-Path $tmp 'manifest.json'
    Download $StableManifestUrl $mf
    $m=Get-Content $mf -Raw|ConvertFrom-Json
    if($m.schema-ne1-or!$m.files){throw 'Unsupported stable manifest.'}
    $stage=Join-Path $StageRoot ([string]$m.release)
    New-Item -ItemType Directory -Force -Path $stage|Out-Null
    $items=Build-Items $m $stage

    $changed=@()
    foreach($item in $items){
      $r=Install-Item $item $mql5 $cfg ([string]$m.release)
      if($r-eq'UPDATED'){
        $changed += $item
        Log "Installed $($item.Role): $($item.TargetName)." 'OK'
      }
    }

    $running=MT5-Running $cfg
    $seqState=Read-RuntimeState $mql5 'sequence_state.txt'
    $bridgeState=Read-RuntimeState $mql5 'bridge_state.txt'

    # If MT5 is running, a changed EA on disk is not assumed to be loaded until runtime state proves it.
    $pending=$false
    if($running){
      if(!$seqState.Data.version -or [string]$seqState.Data.version -ne [string]$m.sequence_ea_version){$pending=$true}
      if(!$bridgeState.Data.version -or [string]$bridgeState.Data.version -ne [string]$m.data_bridge_version){$pending=$true}
      if($seqState.Age -ne $null -and $seqState.Age -gt 45){$pending=$true}
      if($bridgeState.Age -ne $null -and $bridgeState.Age -gt 90){$pending=$true}
    }

    $result=if($pending){'RESTART_REQUIRED'}elseif($running){'CURRENT'}else{'INSTALLED_OFFLINE'}
    $lastAction=if($changed.Count){'FILES_UPDATED'}else{'CHECK_OK'}
    $installed=Write-LocalUpdaterStatus $mql5 $m $result $lastAction $pending

    if($pending -and !$Interactive){
      $did=Try-SafeRestart $cfg $mql5 $pending $seqState
      if($did){
        $result='AUTO_RESTARTED'
        $lastAction='SAFE_AUTO_RESTART'
        $installed=Write-LocalUpdaterStatus $mql5 $m $result $lastAction $true
      }
    }else{
      $script:SafeSince=$null
    }

    $msg=if($pending){
      "Release $($m.release) installed on disk; MT5 runtime reload is required. Auto-restart waits for a fresh restart_safe=1 signal."
    }elseif($running){
      "Release $($m.release) installed and running versions match."
    }else{
      "Release $($m.release) installed. MT5 is offline; next launch will load it."
    }
    Write-StatusJson $cfg $m $result $msg $installed $pending $seqState $bridgeState

    Save-Json ([ordered]@{
      current_release=[string]$m.release;updater_version=$UpdaterVersion
      installed_bridge_version=$installed.Bridge;installed_sequence_version=$installed.Sequence
      pending_reload=$pending;updated_at=(Get-Date).ToString('o')
    }) $StatePath

    if($Interactive){Log $msg $(if($pending){'WARN'}else{'OK'})}
    return 0
  }catch{
    Log "UPDATE ERROR: $($_.Exception.Message)" 'ERROR'
    return 1
  }finally{
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$mutex=New-Object System.Threading.Mutex($false,'TradeZoneUpdaterWorker')
$got=$false
try{$got=$mutex.WaitOne(0)}catch{}
if(!$got){if($Interactive){Log 'Another TradeZone updater worker is already running.' 'WARN'};exit 0}

try{
  if($Interactive){exit (Update-Once)}
  Log "Background watcher v$UpdaterVersion started. Stable channel check every 10 seconds." 'OK'
  $lastUpdaterCheck=[datetime]::MinValue
  while($true){
    $null=Update-Once
    if(((Get-Date)-$lastUpdaterCheck).TotalSeconds-ge60){
      $lastUpdaterCheck=Get-Date
      if(Updater-Superseded){
        Log 'New updater worker published. Handing control back to bootstrap.' 'OK'
        if(Test-Path $BootstrapPath){
          Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-File',$BootstrapPath)|Out-Null
        }
        break
      }
    }
    Start-Sleep -Seconds 10
  }
}finally{
  try{$mutex.ReleaseMutex()}catch{}
  $mutex.Dispose()
}
