param(
  [switch]$Interactive,
  [switch]$Force
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

$BootstrapVersion='1.1.0'
$Repo='Davemafy/icloud'
$Branch='main'
$Root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
$Bin=Join-Path $Root 'bin'
$Log=Join-Path $Root 'updater.log'
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

  Unblock-File -LiteralPath $workerLocal -ErrorAction SilentlyContinue
  $args=@('-NoProfile','-File',$workerLocal)
  if($Interactive){$args+='-Interactive'}
  if($Force){$args+='-Force'}
  $p=Start-Process -FilePath 'powershell.exe' -ArgumentList $args -Wait -PassThru
  exit $p.ExitCode
}catch{
  Write-Log "BOOTSTRAP ERROR: $($_.Exception.Message)"
  $fallback=Join-Path $Bin 'TradeZone_UpdateWorker.ps1'
  if(Test-Path $fallback){
    Unblock-File -LiteralPath $fallback -ErrorAction SilentlyContinue
    $args=@('-NoProfile','-File',$fallback)
    if($Interactive){$args+='-Interactive'}
    if($Force){$args+='-Force'}
    $p=Start-Process -FilePath 'powershell.exe' -ArgumentList $args -Wait -PassThru
    exit $p.ExitCode
  }
  exit 1
}finally{
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
