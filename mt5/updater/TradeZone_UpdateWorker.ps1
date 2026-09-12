param(
  [switch]$Interactive,
  [switch]$Force
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

$UpdaterVersion='2.4.0'
$Repo='Davemafy/icloud'
$Branch='main'
$Root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
$StageRoot=Join-Path $Root 'staging'
$Log=Join-Path $Root 'updater.log'
$StatusPath=Join-Path $Root 'status.json'
$StatePath=Join-Path $Root 'state.json'
$ConfigPath=Join-Path $Root 'config.json'
$StableManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/stable/manifest.json"
New-Item -ItemType Directory -Force -Path $Root,$StageRoot | Out-Null

function Log([string]$Message,[string]$Level='INFO'){
  $line="$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Message"
  Add-Content -Path $Log -Value $line -Encoding UTF8
  if($Interactive){
    $c=if($Level-eq'ERROR'){'Red'}elseif($Level-eq'WARN'){'Yellow'}elseif($Level-eq'OK'){'Green'}else{'Cyan'}
    Write-Host $line -ForegroundColor $c
  }
}
function Save-Json($Object,[string]$Path){$Object|ConvertTo-Json -Depth 8|Set-Content -Path $Path -Encoding UTF8}
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
    $c+=Join-Path $b 'metaeditor64.exe';$c+=Join-Path $b 'MetaEditor64.exe';$c+=Join-Path $b 'metaeditor.exe'
  }
  foreach($r in @($env:ProgramFiles,${env:ProgramFiles(x86)})){
    if($r){$c+=Join-Path $r 'MetaTrader 5\metaeditor64.exe';$c+=Join-Path $r 'MetaTrader 5\MetaEditor64.exe'}
  }
  foreach($p in $c){if($p -and (Test-Path $p)){return $p}}
  return $null
}
function Write-Status([string]$Result,[string]$Message,$Remote=$null){
  $cfg=Load-Json $ConfigPath;$state=Load-Json $StatePath
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
    remote_release=if($Remote){$Remote.release}else{$null}
    sequence_version=if($Remote){$Remote.sequence_ea_version}else{$null}
    bridge_version=if($Remote){$Remote.data_bridge_version}else{$null}
    cloud_status=$cloud
    cloud_version=$cloudVer
  }) $StatusPath
}

$cfg=Load-Json $ConfigPath
if(!$cfg -or !$cfg.target_data_folder){
  $msg='Updater is not configured. Run the ONE installer once.'
  Log $msg 'ERROR';Write-Status 'NEEDS_INSTALLER' $msg;exit 10
}
$mql5=Join-Path ([string]$cfg.target_data_folder) 'MQL5'
if(!(Test-Path $mql5)){
  $msg="Configured MQL5 folder missing: $mql5"
  Log $msg 'ERROR';Write-Status 'TARGET_MISSING' $msg;exit 11
}

$tmp=Join-Path $env:TEMP ('TradeZoneUpdate_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try{
  $mf=Join-Path $tmp 'manifest.json'
  Download $StableManifestUrl $mf
  $m=Get-Content $mf -Raw|ConvertFrom-Json
  if($m.schema-ne1-or!$m.files){throw 'Unsupported stable manifest.'}

  $state=Load-Json $StatePath
  $current=if($state){[string]$state.current_release}else{''}
  if(!$Force -and $current -eq [string]$m.release){
    $msg="Up to date: release $($m.release)."
    Log $msg 'OK';Write-Status 'CURRENT' $msg $m;exit 0
  }

  $stage=Join-Path $StageRoot ([string]$m.release)
  New-Item -ItemType Directory -Force -Path $stage | Out-Null
  $items=@()
  foreach($f in $m.files){
    $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
    $o=Join-Path $stage $f.name
    Download $u $o;Verify $o $f.sha256
    $items += [PSCustomObject]@{Name=[string]$f.name;Path=$o;Target='Experts\TradeZone'}
  }
  if($m.support_files){
    foreach($f in $m.support_files){
      $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
      $o=Join-Path $stage $f.name
      Download $u $o;Verify $o $f.sha256
      $items += [PSCustomObject]@{Name=[string]$f.name;Path=$o;Target=[string]$f.target}
    }
  }
  Log "Release $($m.release) downloaded and verified." 'OK'

  if(MT5-Running $cfg){
    $msg="Release $($m.release) staged. MT5 is running/recently active, so running EAs were not replaced."
    Log $msg 'WARN';Write-Status 'STAGED' $msg $m;exit 0
  }

  $expertDest=Join-Path $mql5 'Experts\TradeZone'
  $compileDir=Join-Path $expertDest ('_staging\'+[string]$m.release)
  New-Item -ItemType Directory -Force -Path $expertDest,$compileDir | Out-Null

  $sources=@()
  foreach($d in $items){
    if($d.Name.ToLowerInvariant().EndsWith('.mq5')){
      $s=Join-Path $compileDir $d.Name
      Copy-Item $d.Path $s -Force;$sources += $s
    }
  }

  $me=Find-MetaEditor $cfg
  if(!$me){throw 'MetaEditor not found. Verified update remains staged.'}
  foreach($src in $sources){
    $ex5=[IO.Path]::ChangeExtension($src,'.ex5')
    $name=[IO.Path]::GetFileNameWithoutExtension($src)
    $clog=Join-Path $compileDir ($name+'_compile.log')
    Log "Compiling $(Split-Path $src -Leaf)"
    Start-Process -FilePath $me -ArgumentList @("/compile:$src","/log:$clog") -Wait|Out-Null
    Start-Sleep -Milliseconds 700
    if(!(Test-Path $ex5)){
      $tail='';if(Test-Path $clog){$tail=(Get-Content $clog -Tail 12)-join' | '}
      throw "Compile failed for $(Split-Path $src -Leaf). Installed EA was left unchanged. $tail"
    }
  }

  $archive=Join-Path $expertDest ('_archive\'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
  $old=@(Get-ChildItem $expertDest -File -ErrorAction SilentlyContinue |
    Where-Object{$_.Name -like 'InstitutionalSMC_DataBridge_v*.*' -or $_.Name -like 'InstitutionalSMC_SequenceEA_v*.*'})
  if($old.Count -gt 0){
    New-Item -ItemType Directory -Force -Path $archive|Out-Null
    foreach($f in $old){
      Move-Item $f.FullName (Join-Path $archive $f.Name) -Force
    }
    Log ("Archived and removed "+$old.Count+" previous active EA file(s) from Navigator root.") 'OK'
  }

  foreach($d in $items){
    $destDir=Join-Path $mql5 $d.Target
    New-Item -ItemType Directory -Force -Path $destDir|Out-Null
    if($d.Name.ToLowerInvariant().EndsWith('.mq5')){
      $s=Join-Path $compileDir $d.Name
      $x=[IO.Path]::ChangeExtension($s,'.ex5')
      Copy-Item $s (Join-Path $destDir $d.Name) -Force
      Copy-Item $x (Join-Path $destDir ([IO.Path]::GetFileName($x))) -Force
    }else{
      Copy-Item $d.Path (Join-Path $destDir $d.Name) -Force
    }
  }

  Save-Json ([ordered]@{
    current_release=[string]$m.release
    sequence_ea_version=[string]$m.sequence_ea_version
    data_bridge_version=[string]$m.data_bridge_version
    installed_at=(Get-Date).ToString('o')
    updater_version=$UpdaterVersion
  }) $StatePath

  $msg="Release $($m.release) installed and compiled successfully."
  Log $msg 'OK';Write-Status 'UPDATED' $msg $m;exit 0
}catch{
  $msg=$_.Exception.Message
  Log "UPDATE ERROR: $msg" 'ERROR';Write-Status 'ERROR' $msg;exit 1
}
