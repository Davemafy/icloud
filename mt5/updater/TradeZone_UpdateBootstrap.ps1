param(
  [switch]$Interactive,
  [switch]$Force
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = 'Davemafy/icloud'
$Branch = 'main'
$Root = Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
$Bin = Join-Path $Root 'bin'
$Log = Join-Path $Root 'updater.log'
$UpdaterManifestUrl = "https://raw.githubusercontent.com/$Repo/$Branch/mt5/updater/manifest.json"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null

function Write-Log([string]$Message) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [bootstrap] $Message"
  Add-Content -Path $Log -Value $line -Encoding UTF8
  if($Interactive){ Write-Host $line }
}
function Download([string]$Url,[string]$Out) {
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 45
  if(!(Test-Path $Out)){ throw "Download failed: $Url" }
}
function Verify([string]$Path,[string]$Expected) {
  $actual=(Get-FileHash -Algorithm SHA256 $Path).Hash.ToLowerInvariant()
  if($actual -ne ([string]$Expected).ToLowerInvariant()){
    throw "SHA256 mismatch for $(Split-Path $Path -Leaf)"
  }
}
function Sync-Component($Def,[string]$LocalPath,[string]$Tmp,[string]$Label) {
  if(!$Def){ return }
  $tempFile=Join-Path $Tmp $Def.name
  $url="https://raw.githubusercontent.com/$Repo/$Branch/$($Def.path)"
  Download $url $tempFile
  Verify $tempFile $Def.sha256
  $replace=$true
  if(Test-Path $LocalPath){
    $localHash=(Get-FileHash -Algorithm SHA256 $LocalPath).Hash.ToLowerInvariant()
    if($localHash -eq ([string]$Def.sha256).ToLowerInvariant()){ $replace=$false }
  }
  if($replace){
    Copy-Item $tempFile $LocalPath -Force
    Write-Log "$Label self-updated."
  }
}

$tmp = Join-Path $env:TEMP ('TradeZoneBootstrap_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
  $mf = Join-Path $tmp 'manifest.json'
  Download $UpdaterManifestUrl $mf
  $m = Get-Content $mf -Raw | ConvertFrom-Json
  if($m.schema -ne 1 -or !$m.worker){ throw 'Unsupported updater manifest.' }

  $workerLocal = Join-Path $Bin $m.worker.name
  Sync-Component $m.worker $workerLocal $tmp "Updater worker v$($m.updater_version)"
  if($m.status){
    $statusLocal=Join-Path $Bin $m.status.name
    Sync-Component $m.status $statusLocal $tmp 'Status tool'
  }

  if($m.bootstrap -and $PSCommandPath){
    Sync-Component $m.bootstrap $PSCommandPath $tmp "Bootstrap v$($m.bootstrap_version)"
  }

  $args=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$workerLocal)
  if($Interactive){ $args += '-Interactive' }
  if($Force){ $args += '-Force' }
  $p=Start-Process -FilePath 'powershell.exe' -ArgumentList $args -Wait -PassThru
  exit $p.ExitCode
}
catch {
  Write-Log "BOOTSTRAP ERROR: $($_.Exception.Message)"
  $fallback = Join-Path $Bin 'TradeZone_UpdateWorker.ps1'
  if(Test-Path $fallback){
    Write-Log 'Using last verified local worker as fallback.'
    $args=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$fallback)
    if($Interactive){$args+='-Interactive'}
    if($Force){$args+='-Force'}
    $p=Start-Process -FilePath 'powershell.exe' -ArgumentList $args -Wait -PassThru
    exit $p.ExitCode
  }
  exit 1
}
finally {
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
