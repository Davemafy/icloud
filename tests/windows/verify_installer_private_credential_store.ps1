# Windows PowerShell 5.1: test encrypted key persistence without MT5 or Cloud.
$ErrorActionPreference='Stop'
$root=Resolve-Path (Join-Path $PSScriptRoot '..\..')
$installer=Get-Content (Join-Path $root 'mt5\installer\Install_TradeZone_MT5.ps1') -Raw
$a=$installer.IndexOf('function TZ_SecretPath(')
$b=$installer.IndexOf("Write-Host '================================================================' -ForegroundColor Cyan",$a)
if($a -lt 0 -or $b -lt $a){throw 'Credential functions missing.'}
Invoke-Expression ($installer.Substring($a,$b-$a))
$original=$env:LOCALAPPDATA
$fixture=Join-Path $env:TEMP ('tz_dpapi_'+[guid]::NewGuid().ToString('N'))
$env:LOCALAPPDATA=$fixture
$cloud='https://fixture.up.railway.app'
$key='TZ_Private_RnD_'+[guid]::NewGuid().ToString('N')
try{
  SaveManagedConfig ([pscustomobject]@{Data='C:\demo';Install='C:\mt5'}) $cloud $key
  $json=Get-Content (Join-Path $fixture 'TradeZoneMT5\config.json') -Raw
  if($json.Contains($key) -or $json.Contains('cloud_api_key')){throw 'Plaintext key leaked.'}
  $blob=Get-Content (TZ_SecretPath $cloud) -Raw
  if($blob.Contains($key)){throw 'DPAPI store has plaintext key.'}
  if((TZ_LoadPrivateCloudKey $cloud) -ne $key){throw 'Installer DPAPI roundtrip failed.'}
  if((TZ_LoadPrivateCloudKey 'https://other.up.railway.app') -ne ''){throw 'Wrong Railway origin reused key.'}
  $lab=Get-Content (Join-Path $root 'mt5\installer\TradeZone_MasterSniper_Backtest_Lab.ps1') -Raw
  $x=$lab.IndexOf('function TZ_SecretPath(')
  $y=$lab.IndexOf('function ReadDate(',$x)
  if($x -lt 0 -or $y -lt $x){throw 'Backtest credential functions missing.'}
  Invoke-Expression ($lab.Substring($x,$y-$x))
  if((TZ_LoadPrivateCloudKey $cloud) -ne $key){throw 'Lab cannot use saved key.'}
  # The actual old-to-new Railway migration: recover an old R&D key
  # from its encrypted store without putting that key into public source.
  $old='https://icloud-production-9111.up.railway.app'
  $new='https://icloud-production-c8d3.up.railway.app'
  $legacyKey='demo_'+[guid]::NewGuid().ToString('N').Substring(0,6)
  $target=[pscustomobject]@{Data='C:\demo';Install='C:\mt5'}
  SaveManagedConfig $target $old $legacyKey
  $oldConfig=Join-Path $fixture 'TradeZoneMT5\config.json'
  if((TZ_LoadMigrationCloudKey $new $oldConfig) -ne $legacyKey){
    throw 'Cannot carry forward encrypted previous Railway credential.'
  }
  if((TZ_LoadMigrationCloudKey 'https://unrelated.up.railway.app' $oldConfig) -ne ''){
    throw 'Credential leaked across unrelated Railway domains.'
  }
  SaveManagedConfig $target $new $legacyKey
  if((TZ_LoadPrivateCloudKey $new) -ne $legacyKey){
    throw 'Migrated R&D key was not saved for new Railway URL.'
  }
  if((Get-Content $oldConfig -Raw).Contains($legacyKey)){
    throw 'R&D migration leaked the key into new config.json.'
  }

  # Back-compat with the previous installer plaintext config format.
  $oldSecret=TZ_SecretPath $old
  Remove-Item -LiteralPath $oldSecret -Force
  @{
    target_data_folder='C:\demo'
    mt5_install_path='C:\mt5'
    cloud_url=$old
    cloud_api_key=$legacyKey
  }|ConvertTo-Json|Set-Content -LiteralPath $oldConfig -Encoding UTF8
  if((TZ_LoadMigrationCloudKey $new $oldConfig) -ne $legacyKey){
    throw 'Cannot migrate previous installer legacy plaintext credential.'
  }
  Write-Host 'PASS: DPAPI encrypted store, Backtest Lab, and old-to-new R&D migration.' -ForegroundColor Green
}finally{
  $env:LOCALAPPDATA=$original
  Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
}
