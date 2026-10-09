$ErrorActionPreference='Stop'
$repo=Resolve-Path (Join-Path $PSScriptRoot '..\..')
$installer=Join-Path $repo 'mt5\installer\Install_TradeZone_MT5.ps1'
$src=Get-Content -LiteralPath $installer -Raw -ErrorAction Stop

# Execute the ACTUAL installation-status section with an isolated fake MT5 data folder.
# Never start MetaTrader, access GitHub, compile, or contact the real cloud.
$begin=$src.IndexOf('  $statusDir=Join-Path $t.MQL5')
$end=$src.IndexOf('  SaveManagedConfig $t $cloudUrl $cloudKey', $begin)
if($begin -lt 0 -or $end -lt 0){throw 'Installer status writer boundaries changed.'}
$isolatedBlock=$src.Substring($begin,$end-$begin)
$mt5Folder=Join-Path $env:TEMP ('tz_status_test_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $mt5Folder -Force | Out-Null
try {
  $t=[pscustomobject]@{MQL5=$mt5Folder}
  $m=[pscustomobject]@{
    release='6.4.20'
    data_bridge_version='1.59'
    sequence_ea_version='3.78'
  }
  $InstallerVersion='FRONT_FACING_MANUAL_INSTALLER_1.11'
  Invoke-Expression $isolatedBlock
  $path=Join-Path $mt5Folder 'Files\TradeZone\updater_status.txt'
  if(!(Test-Path -LiteralPath $path)){throw 'MT5 status file not created.'}
  $lines=@(Get-Content -LiteralPath $path -ErrorAction Stop)
  if($lines.Count -ne 10){throw "Expected TEN physical lines; found $($lines.Count): $($lines -join ' | ')"}

  $expected=@(
    'updater_version=FRONT_FACING_MANUAL_INSTALLER_1.11',
    'stable_release=6.4.20',
    'desired_bridge_version=1.59',
    'desired_sequence_version=3.78',
    'installed_bridge_version=1.59',
    'installed_sequence_version=3.78',
    'pending_reload=1',
    'result=INSTALLED_REATTACH_REQUIRED',
    'update_result=INSTALLED_REATTACH_REQUIRED'
  )
  foreach($line in $expected) {
    if($lines -notcontains $line){throw "Missing or merged status line: $line"}
  }
  $receipts=@($lines | Where-Object { $_ -match '^last_action=MANUAL_INSTALL_COMPILED_[0-9a-f]{32}$' })
  if($receipts.Count -ne 1){throw 'Exactly one unique per-installation receipt is required.'}
  foreach($line in $lines){
    if($line -match 'updater_version=.*stable_release='){throw 'Multiple status fields were merged together.'}
    if($line -notmatch '^[a-z_]+=[^\r\n]*$'){throw "Malformed status field: $line"}
  }
  Write-Host 'REAL INSTALLER STATUS WRITE / READBACK TEST PASSED: ten separate fields, unique receipt.' -ForegroundColor Green
}
finally {
  Remove-Item -LiteralPath $mt5Folder -Recurse -Force -ErrorAction SilentlyContinue
}
