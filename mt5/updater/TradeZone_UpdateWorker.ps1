param(
  [switch]$Interactive,
  [switch]$Force
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

$UpdaterVersion='2.5.0'
$Repo='Davemafy/icloud'
$Branch='main'
$Root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
$Bin=Join-Path $Root 'bin'
$StageRoot=Join-Path $Root 'staging'
$Log=Join-Path $Root 'updater.log'
$StatusPath=Join-Path $Root 'status.json'
$StatePath=Join-Path $Root 'state.json'
$ConfigPath=Join-Path $Root 'config.json'
$StableManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/stable/manifest.json"
$UpdaterManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/updater/manifest.json"
$BootstrapPath=Join-Path $Bin 'TradeZone_UpdateBootstrap.ps1'
New-Item -ItemType Directory -Force -Path $Root,$StageRoot,$Bin | Out-Null

function Log([string]$Message,[string]$Level='INFO'){
  $line="$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Message"
  Add-Content -Path $Log -Value $line -Encoding UTF8
  if($Interactive){
    $c=if($Level-eq'ERROR'){'Red'}elseif($Level-eq'WARN'){'Yellow'}elseif($Level-eq'OK'){'Green'}else{'Cyan'}
    Write-Host $line -ForegroundColor $c
  }
}
function Save-Json($Object,[string]$Path){$Object|ConvertTo-Json -Depth 10|Set-Content -Path $Path -Encoding UTF8}
function Load-Json([string]$Path){if(Test-Path $Path){try{return (Get-Content $Path -Raw|ConvertFrom-Json)}catch{}};return $null}
function Download([string]$Url,[string]$Out){
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 45
  if(!(Test-Path $Out)){throw "Download failed: $Url"}
}
function Verify([string]$Path,[string]$Expected){
  $actual=(Get-FileHash -Algorithm SHA256 $Path).Hash.ToLowerInvariant()
  if($actual-ne([string]$Expected).ToLowerInvariant()){throw "SHA256 verification failed for $(Split-Path $Path -Leaf)"}
}
function Newest-LogTime([string]$DataFolder){
  $best=[datetime]::MinValue
  foreach($p in @((Join-Path $DataFolder 'logs'),(Join-Path $DataFolder 'MQL5\Logs'))){
    if(Test-Path $p){
      try{
        $f=Get-ChildItem $p -File -Recurse -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if($f -and $f.LastWriteTime -gt $best){$best=$f.LastWriteTime}
      }catch{}
    }
  }
  return $best
}
function MT5-Running($cfg){
  try{
    if(Get-Process -ErrorAction SilentlyContinue | Where-Object{$_.ProcessName -match '^(terminal|terminal64)$'}){return $true}
  }catch{}
  try{
    if(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object{$_.Name -match '^(terminal|terminal64)\.exe$'}){return $true}
  }catch{}
  if($cfg -and $cfg.target_data_folder){
    $last=Newest-LogTime ([string]$cfg.target_data_folder)
    if($last -gt [datetime]::MinValue){
      $age=((Get-Date)-$last).TotalMinutes
      if($age -le 2){return $true}
    }
  }
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
function Write-Status([string]$Result,[string]$Message,$Remote=$null){
  $cfg=Load-Json $ConfigPath
  $state=Load-Json $StatePath
  $cloud='UNKNOWN';$cloudVer=$null
  if($cfg -and $cfg.cloud_url){
    try{
      $h=Invoke-RestMethod -Uri (($cfg.cloud_url.TrimEnd('/'))+'/health') -TimeoutSec 8
      if($h.ok){$cloud='ONLINE'}else{$cloud='DEGRADED'}
      if($h.version){$cloudVer=[string]$h.version}
    }catch{$cloud='UNREACHABLE'}
  }
  Save-Json ([ordered]@{
    checked_at=(Get-Date).ToString('o')
    result=$Result
    message=$Message
    updater_version=$UpdaterVersion
    target_data_folder=if($cfg){$cfg.target_data_folder}else{$null}
    installed_release=if($state){$state.current_release}else{$null}
    staged_release=if($state){$state.staged_release}else{$null}
    remote_release=if($Remote){$Remote.release}else{$null}
    sequence_version=if($Remote){$Remote.sequence_ea_version}else{$null}
    bridge_version=if($Remote){$Remote.data_bridge_version}else{$null}
    cloud_status=$cloud
    cloud_version=$cloudVer
    watch_mode=if($Interactive){'ONE_SHOT'}else{'CONTINUOUS_10S'}
  }) $StatusPath
}
function Target-IsCurrent($item,[string]$mql5){
  $destDir=Join-Path $mql5 $item.Target
  $dest=Join-Path $destDir $item.TargetName
  if(!(Test-Path $dest)){return $false}
  try{
    $h=(Get-FileHash -Algorithm SHA256 $dest).Hash.ToLowerInvariant()
    if($h-ne $item.Sha.ToLowerInvariant()){return $false}
  }catch{return $false}
  if($item.TargetName.ToLowerInvariant().EndsWith('.mq5')){
    $ex5=[IO.Path]::ChangeExtension($dest,'.ex5')
    if(!(Test-Path $ex5)){return $false}
  }
  return $true
}
function Archive-One([string]$Path,[string]$ArchiveDir){
  if(Test-Path $Path){
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    Copy-Item $Path (Join-Path $ArchiveDir (Split-Path $Path -Leaf)) -Force
  }
}
function Install-Item($item,[string]$mql5,$cfg,[bool]$mt5Running,[string]$release){
  if(Target-IsCurrent $item $mql5){return 'CURRENT'}
  if($mt5Running -and !$item.HotReloadSafe){
    return 'STAGED'
  }

  $destDir=Join-Path $mql5 $item.Target
  New-Item -ItemType Directory -Force -Path $destDir | Out-Null
  $archive=Join-Path (Join-Path $mql5 'Experts\TradeZone\_archive') (Get-Date -Format 'yyyyMMdd_HHmmss_fff')

  if($item.TargetName.ToLowerInvariant().EndsWith('.mq5')){
    $compileDir=Join-Path (Join-Path $mql5 'Experts\TradeZone\_staging') $release
    New-Item -ItemType Directory -Force -Path $compileDir | Out-Null
    $src=Join-Path $compileDir $item.TargetName
    Copy-Item $item.DownloadPath $src -Force

    $me=Find-MetaEditor $cfg
    if(!$me){throw "MetaEditor not found. $($item.TargetName) remains staged."}
    $ex5=[IO.Path]::ChangeExtension($src,'.ex5')
    $name=[IO.Path]::GetFileNameWithoutExtension($src)
    $clog=Join-Path $compileDir ($name+'_compile.log')
    Log "Compiling $($item.TargetName)"
    Start-Process -FilePath $me -ArgumentList @("/compile:$src","/log:$clog") -Wait | Out-Null
    Start-Sleep -Milliseconds 700
    if(!(Test-Path $ex5)){
      $tail=''
      if(Test-Path $clog){$tail=(Get-Content $clog -Tail 12)-join' | '}
      throw "Compile failed for $($item.TargetName). Existing EA left unchanged. $tail"
    }

    $destMq5=Join-Path $destDir $item.TargetName
    $destEx5=[IO.Path]::ChangeExtension($destMq5,'.ex5')
    Archive-One $destMq5 $archive
    Archive-One $destEx5 $archive
    Copy-Item $src $destMq5 -Force
    Copy-Item $ex5 $destEx5 -Force
    return $(if($mt5Running){'HOT_UPDATED'}else{'UPDATED'})
  } else {
    $dest=Join-Path $destDir $item.TargetName
    Archive-One $dest $archive
    Copy-Item $item.DownloadPath $dest -Force
    return 'UPDATED'
  }
}
function Build-Items($m,[string]$stage){
  $items=@()
  foreach($f in $m.files){
    $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
    $o=Join-Path $stage $f.name
    Download $u $o
    Verify $o $f.sha256
    $targetName=if($f.target_name){[string]$f.target_name}else{[string]$f.name}
    $hot=$false
    if($null-ne $f.hot_reload_safe){$hot=[bool]$f.hot_reload_safe}
    $items += [PSCustomObject]@{
      Role=[string]$f.role
      SourceName=[string]$f.name
      TargetName=$targetName
      DownloadPath=$o
      Sha=[string]$f.sha256
      Target='Experts\TradeZone'
      HotReloadSafe=$hot
    }
  }
  if($m.support_files){
    foreach($f in $m.support_files){
      $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
      $o=Join-Path $stage $f.name
      Download $u $o
      Verify $o $f.sha256
      $targetName=if($f.target_name){[string]$f.target_name}else{[string]$f.name}
      $items += [PSCustomObject]@{
        Role='support'
        SourceName=[string]$f.name
        TargetName=$targetName
        DownloadPath=$o
        Sha=[string]$f.sha256
        Target=[string]$f.target
        HotReloadSafe=$true
      }
    }
  }
  return @($items)
}
function Update-Once {
  $cfg=Load-Json $ConfigPath
  if(!$cfg -or !$cfg.target_data_folder){
    $msg='Updater is not configured. Run the ONE installer once.'
    Log $msg 'ERROR';Write-Status 'NEEDS_INSTALLER' $msg;return 10
  }
  $mql5=Join-Path ([string]$cfg.target_data_folder) 'MQL5'
  if(!(Test-Path $mql5)){
    $msg="Configured MQL5 folder missing: $mql5"
    Log $msg 'ERROR';Write-Status 'TARGET_MISSING' $msg;return 11
  }

  $tmp=Join-Path $env:TEMP ('TradeZoneUpdate_'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  try{
    $mf=Join-Path $tmp 'manifest.json'
    Download $StableManifestUrl $mf
    $m=Get-Content $mf -Raw|ConvertFrom-Json
    if($m.schema-ne1-or!$m.files){throw 'Unsupported stable manifest.'}

    $stage=Join-Path $StageRoot ([string]$m.release)
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    $items=Build-Items $m $stage

    $running=MT5-Running $cfg
    $results=@()
    foreach($item in $items){
      $r=Install-Item $item $mql5 $cfg $running ([string]$m.release)
      $results += [PSCustomObject]@{Role=$item.Role;Name=$item.TargetName;Result=$r}
      if($r -eq 'HOT_UPDATED'){Log "Hot-updated $($item.Role): $($item.TargetName) while MT5 was running." 'OK'}
      elseif($r -eq 'UPDATED'){Log "Updated $($item.Role): $($item.TargetName)." 'OK'}
      elseif($r -eq 'STAGED'){Log "Staged $($item.Role): $($item.TargetName) until a safe runtime reload." 'WARN'}
    }

    $pending=@($results | Where-Object{$_.Result -eq 'STAGED'})
    $state=Load-Json $StatePath
    if(!$state){$state=[PSCustomObject]@{}}

    if($pending.Count -eq 0){
      Save-Json ([ordered]@{
        current_release=[string]$m.release
        staged_release=$null
        sequence_ea_version=[string]$m.sequence_ea_version
        data_bridge_version=[string]$m.data_bridge_version
        installed_at=(Get-Date).ToString('o')
        updater_version=$UpdaterVersion
      }) $StatePath
      $msg="Release $($m.release) is current. All approved components installed."
      Write-Status 'CURRENT' $msg $m
      if($Interactive){Log $msg 'OK'}
    } else {
      Save-Json ([ordered]@{
        current_release=if($state.current_release){[string]$state.current_release}else{$null}
        staged_release=[string]$m.release
        sequence_ea_version=if($state.sequence_ea_version){[string]$state.sequence_ea_version}else{$null}
        data_bridge_version=[string]$m.data_bridge_version
        staged_at=(Get-Date).ToString('o')
        updater_version=$UpdaterVersion
      }) $StatePath
      $names=($pending|ForEach-Object{$_.Name}) -join ', '
      $msg="Release $($m.release) partially installed. Runtime-sensitive component(s) staged: $names"
      Write-Status 'PARTIAL_STAGED' $msg $m
      if($Interactive){Log $msg 'WARN'}
    }
    return 0
  }catch{
    $msg=$_.Exception.Message
    Log "UPDATE ERROR: $msg" 'ERROR'
    Write-Status 'ERROR' $msg
    return 1
  }finally{
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
}
function Updater-Superseded {
  try{
    $m=Invoke-RestMethod -Uri $UpdaterManifestUrl -TimeoutSec 15
    return ([string]$m.updater_version -ne $UpdaterVersion)
  }catch{return $false}
}

if($Interactive){
  $rc=Update-Once
  exit $rc
}

Log "Background watcher v$UpdaterVersion started. Stable channel check every 10 seconds." 'OK'
$lastUpdaterCheck=[datetime]::MinValue
while($true){
  $null=Update-Once
  if(((Get-Date)-$lastUpdaterCheck).TotalSeconds -ge 60){
    $lastUpdaterCheck=Get-Date
    if(Updater-Superseded){
      Log "A newer updater worker is published. Handing control back to bootstrap." 'OK'
      if(Test-Path $BootstrapPath){
        Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-File',$BootstrapPath) | Out-Null
      }
      exit 0
    }
  }
  Start-Sleep -Seconds 10
}
