$ErrorActionPreference='SilentlyContinue'
$Root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
$Cfg=Join-Path $Root 'config.json'
$Status=Join-Path $Root 'status.json'
function KV([string]$p){
  $o=[ordered]@{}
  if(Test-Path $p){
    foreach($line in Get-Content $p){
      $i=$line.IndexOf('=')
      if($i-gt0){$o[$line.Substring(0,$i)]=$line.Substring($i+1)}
    }
  }
  return [pscustomobject]$o
}
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' Trade Zone - Component / Update Status' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
if(!(Test-Path $Cfg)){Write-Host 'TradeZone updater is not configured.' -ForegroundColor Red;Read-Host 'ENTER';exit}
$c=Get-Content $Cfg -Raw|ConvertFrom-Json
$mql5=Join-Path ([string]$c.target_data_folder) 'MQL5'
$u=KV (Join-Path $mql5 'Files\TradeZone\updater_status.txt')
$b=KV (Join-Path $mql5 'Files\TradeZone\bridge_state.txt')
$s=KV (Join-Path $mql5 'Files\TradeZone\sequence_state.txt')
Write-Host ("Stable release    : "+$u.stable_release)
Write-Host ("Updater worker    : "+$u.updater_version)
Write-Host ("Last update result: "+$u.result)
Write-Host ("Pending reload    : "+$u.pending_reload)
Write-Host ''
Write-Host 'DataBridge'
Write-Host ("  GitHub desired  : "+$u.desired_bridge_version)
Write-Host ("  Installed disk  : "+$u.installed_bridge_version)
Write-Host ("  Running         : "+$b.version)
Write-Host ''
Write-Host 'Sequence EA'
Write-Host ("  GitHub desired  : "+$u.desired_sequence_version)
Write-Host ("  Installed disk  : "+$u.installed_sequence_version)
Write-Host ("  Running         : "+$s.version)
Write-Host ("  Restart safe    : "+$s.restart_safe)
Write-Host ("  Open positions  : "+$s.open_positions)
Write-Host ("  Analysis / zone : "+$s.analysis_id+" / "+$s.zone_id)
Write-Host ''
if($u.pending_reload-eq'1'){
  if($s.restart_safe-eq'1'){Write-Host 'STATE: UPDATE INSTALLED — SAFE AUTO-RELOAD SHOULD OCCUR.' -ForegroundColor Yellow}
  else{Write-Host 'STATE: UPDATE INSTALLED — WAITING FOR SAFE RELOAD.' -ForegroundColor Yellow}
}else{
  Write-Host 'STATE: COMPONENTS CURRENT.' -ForegroundColor Green
}
Write-Host ''
Write-Host ("Log: "+(Join-Path $Root 'updater.log')) -ForegroundColor DarkGray
Read-Host 'Press ENTER to close'
