param(
  [switch]$Interactive,
  [switch]$Force
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

$UpdaterVersion='2.7.0'
$CoreVersion='2.6.0'
$Repo='Davemafy/icloud'
$Branch='main'
$CoreCommit='8d772971c8c7a9cbefb6719a730e2663d5bd73e8'
$CoreSha256='871fe6a8359cf1b79be892df4247be9966a2b6699363f883d8864f5386a615c9'

$Root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
$Bin=Join-Path $Root 'bin'
$Log=Join-Path $Root 'updater.log'
$ConfigPath=Join-Path $Root 'config.json'
$StatusPath=Join-Path $Root 'status.json'
$SupervisorState=Join-Path $Root 'supervisor_state.json'
$BootstrapPath=Join-Path $Bin 'TradeZone_UpdateBootstrap.ps1'
$CorePath=Join-Path $Bin 'TradeZone_UpdateWorkerCore_v2_6.ps1'
$UpdaterManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/updater/manifest.json"
$CoreUrl="https://raw.githubusercontent.com/$Repo/$CoreCommit/mt5/updater/TradeZone_UpdateWorker.ps1"

New-Item -ItemType Directory -Force -Path $Root,$Bin | Out-Null

function Log([string]$Message,[string]$Level='INFO'){
  $line="$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [supervisor $UpdaterVersion][$Level] $Message"
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
  Unblock-File -LiteralPath $Out -ErrorAction SilentlyContinue
}
function Verify([string]$Path,[string]$Expected){
  $actual=(Get-FileHash -Algorithm SHA256 $Path).Hash.ToLowerInvariant()
  if($actual-ne$Expected.ToLowerInvariant()){throw "SHA256 mismatch for $(Split-Path $Path -Leaf)"}
}
function Ensure-Core(){
  $ok=$false
  if(Test-Path $CorePath){
    try{$ok=((Get-FileHash -Algorithm SHA256 $CorePath).Hash.ToLowerInvariant()-eq$CoreSha256)}catch{}
  }
  if(!$ok){
    $tmp=Join-Path $env:TEMP ('TradeZoneCore_'+[guid]::NewGuid().ToString('N')+'.ps1')
    try{
      Download $CoreUrl $tmp
      Verify $tmp $CoreSha256
      Copy-Item $tmp $CorePath -Force
      Unblock-File -LiteralPath $CorePath -ErrorAction SilentlyContinue
      Log "Pinned update core v$CoreVersion downloaded and verified." 'OK'
    }finally{
      Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
  }
}
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
    if($match.Count-eq1){return $match[0]}
  }
  if($rows.Count-eq1){return $rows[0]}
  return $null
}
function Invoke-CoreOnce(){
  Ensure-Core
  $before=Load-Json $StatusPath
  $beforeTime=if($before){[string]$before.checked_at}else{''}
  $args=@('-NoProfile','-File',$CorePath,'-Interactive','-Force')
  $p=Start-Process -FilePath 'powershell.exe' -ArgumentList $args -WindowStyle Hidden -Wait -PassThru
  Start-Sleep -Milliseconds 300
  $s=Load-Json $StatusPath
  if(!$s){
    Log "Core v$CoreVersion returned $($p.ExitCode) but no updater status was written." 'WARN'
  }elseif([string]$s.checked_at-eq$beforeTime){
    Log "Core v$CoreVersion did not refresh status; another core process may still be exiting." 'WARN'
  }
  return $s
}
function Is-PaperOnly($cfg){
  if(!$cfg){return $false}
  if($cfg.paper_only -is [bool]){return [bool]$cfg.paper_only}
  return ([string]$cfg.paper_only).Trim().ToLowerInvariant() -in @('1','true','yes','on')
}
function Graceful-Restart($cfg,[string]$Reason){
  $managed=Get-ManagedTerminalProcess $cfg
  if(!$managed){
    Log "Restart requested ($Reason) but exactly one managed MT5 process could not be identified." 'WARN'
    return $false
  }
  try{$p=Get-Process -Id $managed.Pid -ErrorAction Stop}catch{return $false}
  $exe=$managed.Exe
  Log "Requesting graceful MT5 restart for PID $($managed.Pid): $Reason" 'OK'
  $accepted=$false
  try{$accepted=$p.CloseMainWindow()}catch{}
  if(!$accepted){
    Log 'MT5 did not accept graceful close. No force-kill will be used.' 'WARN'
    return $false
  }
  try{Wait-Process -Id $managed.Pid -Timeout 25 -ErrorAction Stop}catch{
    Log 'MT5 did not close within 25 seconds. No force-kill will be used.' 'WARN'
    return $false
  }
  Start-Sleep -Seconds 2
  try{
    Start-Process -FilePath $exe | Out-Null
    Log 'MT5 relaunched. Attached charts can now load the installed EA build.' 'OK'
    return $true
  }catch{
    Log "MT5 closed but relaunch failed: $($_.Exception.Message)" 'ERROR'
    return $false
  }
}
function Maybe-Reload($cfg,$status){
  if(!$status -or !$status.pending_reload){return $false}
  $release=[string]$status.stable_release
  if([string]::IsNullOrWhiteSpace($release)){$release='UNKNOWN'}
  $state=Load-Json $SupervisorState
  $already=if($state){[string]$state.last_restart_release}else{''}
  if($already-eq$release){return $false}

  $runningSeq=[string]$status.running_sequence_version
  $restartSafe=([string]$status.restart_safe -eq '1')

  if($runningSeq -and $restartSafe){
    Log "Sequence runtime $runningSeq reports restart_safe=1. Arming safe reload for $release." 'OK'
    Start-Sleep -Seconds 20
    $status2=Invoke-CoreOnce
    if(!$status2 -or !$status2.pending_reload){return $false}
    if([string]$status2.restart_safe-ne'1'){Log 'Safe state changed during hold; reload cancelled.' 'WARN';return $false}
    if(Graceful-Restart $cfg "safe runtime reload for release $release"){
      Save-Json ([ordered]@{last_restart_release=$release;reason='SAFE_RUNTIME';at=(Get-Date).ToString('o')}) $SupervisorState
      return $true
    }
    return $false
  }

  if(!$runningSeq -and (Is-PaperOnly $cfg)){
    Log "First-transition activation needed for $release; legacy Sequence has no restart_safe telemetry." 'WARN'
    Start-Sleep -Seconds 20
    $status2=Invoke-CoreOnce
    if(!$status2 -or !$status2.pending_reload){return $false}
    if([string]$status2.running_sequence_version){
      Log 'Sequence runtime appeared during hold; returning to normal safe-reload gate.' 'INFO'
      return $false
    }
    if(Graceful-Restart $cfg "one-time DEMO/PAPER first-transition activation for release $release"){
      Save-Json ([ordered]@{last_restart_release=$release;reason='FIRST_TRANSITION_DEMO';at=(Get-Date).ToString('o')}) $SupervisorState
      return $true
    }
  }
  return $false
}
function Updater-Superseded(){
  try{
    $u=Invoke-RestMethod -Uri $UpdaterManifestUrl -TimeoutSec 15
    return ([string]$u.updater_version-ne$UpdaterVersion)
  }catch{return $false}
}

$mutex=New-Object System.Threading.Mutex($false,'TradeZoneUpdaterSupervisor')
$got=$false
try{$got=$mutex.WaitOne(15000)}catch{}
if(!$got){if($Interactive){Log 'Another TradeZone updater supervisor is already running.' 'WARN'};exit 0}

try{
  $cfg=Load-Json $ConfigPath
  if(!$cfg){
    Log 'Updater config is missing. Existing one-time installer/configuration is required.' 'ERROR'
    exit 10
  }

  if($Interactive){
    $s=Invoke-CoreOnce
    $restarted=Maybe-Reload $cfg $s
    if($restarted){Start-Sleep -Seconds 12;$null=Invoke-CoreOnce}
    exit 0
  }

  Log "Supervisor v$UpdaterVersion started. GitHub/stable check every 10 seconds." 'OK'
  $lastUpdaterCheck=[datetime]::MinValue
  while($true){
    $s=Invoke-CoreOnce
    $restarted=Maybe-Reload $cfg $s
    if($restarted){
      Start-Sleep -Seconds 15
      $null=Invoke-CoreOnce
    }

    if(((Get-Date)-$lastUpdaterCheck).TotalSeconds-ge60){
      $lastUpdaterCheck=Get-Date
      if(Updater-Superseded){
        Log 'New updater version published. Handing control back to bootstrap.' 'OK'
        if(Test-Path $BootstrapPath){
          Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-File',$BootstrapPath) -WindowStyle Hidden | Out-Null
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
