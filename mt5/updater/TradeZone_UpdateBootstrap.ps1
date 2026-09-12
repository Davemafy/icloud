param(
  [switch]$Interactive,
  [switch]$Force
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

$BootstrapVersion='1.3.0'
$Repo='Davemafy/icloud'
$Branch='main'
$Root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
$Bin=Join-Path $Root 'bin'
$Log=Join-Path $Root 'updater.log'
$ConfigPath=Join-Path $Root 'config.json'
$DefaultCloudUrl='https://icloud-production-9111.up.railway.app'
$TaskName='TradeZone MT5 Background Updater'
$SilentLauncher=Join-Path $Bin 'TradeZone_UpdateSilent.vbs'
$UpdaterManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/updater/manifest.json"
New-Item -ItemType Directory -Force -Path $Bin|Out-Null

function Write-Log([string]$Message){
  $line="$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [bootstrap $BootstrapVersion] $Message"
  Add-Content -Path $Log -Value $line -Encoding UTF8
  if($Interactive){Write-Host $line}
}
function Download([string]$Url,[string]$Out){
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 45
  if(!(Test-Path $Out)){throw "Download failed: $Url"}
  Unblock-File -LiteralPath $Out -ErrorAction SilentlyContinue
}
function Verify([string]$Path,[string]$Expected){
  $actual=(Get-FileHash -Algorithm SHA256 $Path).Hash.ToLowerInvariant()
  if($actual-ne([string]$Expected).ToLowerInvariant()){throw "SHA256 mismatch for $(Split-Path $Path -Leaf)"}
}
function Sync-Component($Def,[string]$LocalPath,[string]$Tmp,[string]$Label){
  if(!$Def){return}
  $temp=Join-Path $Tmp $Def.name
  $url="https://raw.githubusercontent.com/$Repo/$Branch/$($Def.path)"
  Download $url $temp;Verify $temp $Def.sha256
  $replace=$true
  if(Test-Path $LocalPath){
    try{$replace=((Get-FileHash -Algorithm SHA256 $LocalPath).Hash.ToLowerInvariant()-ne([string]$Def.sha256).ToLowerInvariant())}catch{}
  }
  if($replace){
    Copy-Item $temp $LocalPath -Force
    Unblock-File -LiteralPath $LocalPath -ErrorAction SilentlyContinue
    Write-Log "$Label updated and verified."
  }
}
function Ensure-PaperOnlyConfigFromCloud(){
  if(!(Test-Path $ConfigPath)){
    Write-Log 'Legacy gate migration skipped: updater config.json is missing.'
    return
  }

  try{$cfg=Get-Content $ConfigPath -Raw|ConvertFrom-Json}catch{
    Write-Log "Legacy gate migration skipped: config.json could not be read: $($_.Exception.Message)"
    return
  }

  $existing=$false
  if($cfg.PSObject.Properties.Name -contains 'paper_only'){
    if($cfg.paper_only -is [bool]){$existing=[bool]$cfg.paper_only}
    else{$existing=([string]$cfg.paper_only).Trim().ToLowerInvariant() -in @('1','true','yes','on')}
  }
  if($existing){return}

  $cloud=$DefaultCloudUrl
  if($cfg.PSObject.Properties.Name -contains 'cloud_url'){
    $candidate=[string]$cfg.cloud_url
    if(![string]::IsNullOrWhiteSpace($candidate)){$cloud=$candidate.TrimEnd('/')}
  }

  try{
    $h=Invoke-RestMethod -Uri ($cloud+'/health') -TimeoutSec 10
    $paper=($h.paper_only -eq $true -or ([string]$h.paper_only).Trim().ToLowerInvariant() -in @('1','true','yes','on'))
    if($h.ok -eq $true -and $paper){
      $cfg|Add-Member -NotePropertyName paper_only -NotePropertyValue $true -Force
      $cfg|ConvertTo-Json -Depth 10|Set-Content -Path $ConfigPath -Encoding UTF8
      Write-Log "Legacy first-transition gate repaired: cloud $cloud verified PAPER_ONLY=true and config.paper_only was set to true."
    }else{
      Write-Log "Legacy first-transition gate remains blocked: cloud $cloud did not confirm PAPER_ONLY=true."
    }
  }catch{
    Write-Log "Legacy first-transition gate remains blocked: cloud PAPER_ONLY verification failed at $cloud: $($_.Exception.Message)"
  }
}
function Ensure-SilentTask(){
  # WScript is a GUI host, so the 5-minute recovery task runs with no PowerShell window flash.
  $vbs=@'
Option Explicit
Dim sh, root, boot, cmd
Set sh = CreateObject("WScript.Shell")
root = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%")
boot = root & "\TradeZoneMT5\bin\TradeZone_UpdateBootstrap.ps1"
cmd = "powershell.exe -NoProfile -WindowStyle Hidden -File """ & boot & """"
sh.Run cmd, 0, False
'@
  Set-Content -Path $SilentLauncher -Value $vbs -Encoding ASCII

  try{
    & schtasks.exe /Query /TN $TaskName 2>$null | Out-Null
    if($LASTEXITCODE -eq 0){
      $action='wscript.exe //B //Nologo "'+$SilentLauncher+'"'
      & schtasks.exe /Change /TN $TaskName /TR $action 2>$null | Out-Null
      if($LASTEXITCODE -eq 0){
        Write-Log 'Scheduled updater task switched to silent background launcher.'
      }else{
        Write-Log 'Could not switch scheduled task to silent launcher; existing task was left unchanged.'
      }
    }else{
      Write-Log 'Scheduled updater task was not found; silent launcher was prepared for the next installer/repair.'
    }
  }catch{
    Write-Log "Silent-task repair warning: $($_.Exception.Message)"
  }
}
function Run-Worker([string]$Worker,[bool]$WaitForExit){
  Unblock-File -LiteralPath $Worker -ErrorAction SilentlyContinue
  $args=@('-NoProfile','-File',$Worker)
  if($Interactive){$args+='-Interactive'}
  if($Force){$args+='-Force'}

  if($Interactive){
    $p=Start-Process -FilePath 'powershell.exe' -ArgumentList $args -Wait -PassThru
    return $p.ExitCode
  }

  # Background launches are deliberately hidden.
  $p=Start-Process -FilePath 'powershell.exe' -ArgumentList $args -WindowStyle Hidden -PassThru
  if($WaitForExit){
    $p.WaitForExit()
    return $p.ExitCode
  }
  return 0
}

$tmp=Join-Path $env:TEMP ('TradeZoneBootstrap_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp|Out-Null
try{
  $mf=Join-Path $tmp 'manifest.json'
  Download $UpdaterManifestUrl $mf
  $m=Get-Content $mf -Raw|ConvertFrom-Json
  if($m.schema-ne1-or!$m.worker){throw 'Unsupported updater manifest.'}

  $workerLocal=Join-Path $Bin $m.worker.name
  Sync-Component $m.worker $workerLocal $tmp "Updater worker v$($m.updater_version)"
  if($m.status){
    Sync-Component $m.status (Join-Path $Bin $m.status.name) $tmp 'Status tool'
  }
  if($m.bootstrap -and $PSCommandPath){
    Sync-Component $m.bootstrap $PSCommandPath $tmp "Bootstrap v$($m.bootstrap_version)"
  }

  Ensure-PaperOnlyConfigFromCloud
  Ensure-SilentTask

  $code=Run-Worker $workerLocal $true
  exit $code
}catch{
  Write-Log "BOOTSTRAP ERROR: $($_.Exception.Message)"
  $fallback=Join-Path $Bin 'TradeZone_UpdateWorker.ps1'
  if(Test-Path $fallback){
    Write-Log 'Using last verified local worker as fallback.'
    $code=Run-Worker $fallback $true
    exit $code
  }
  exit 1
}finally{
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
