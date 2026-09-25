$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle='Trade Zone - Sniper Parity Validator'

$Repo='Davemafy/icloud'
$Branch='sniper-contract-parity-v1'
$Raw="https://raw.githubusercontent.com/$Repo/$Branch"

function PauseExit([int]$Code=0){Write-Host '';Read-Host 'Press ENTER to close';exit $Code}
function Download([string]$Url,[string]$Out){Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 60;if(!(Test-Path $Out)){throw "Download failed: $Url"};Unblock-File -LiteralPath $Out -ErrorAction SilentlyContinue}
function DiscoverTargets(){
  $root=Join-Path $env:APPDATA 'MetaQuotes\Terminal';if(!(Test-Path $root)){throw 'MT5 terminal data root not found.'}
  $inst=@();Get-ChildItem $root -Directory|ForEach-Object{$mq=Join-Path $_.FullName 'MQL5';if(Test-Path $mq){$or=Join-Path $_.FullName 'origin.txt';$ip=$null;if(Test-Path $or){try{$ip=(Get-Content $or -Raw).Trim()}catch{}};$inst+=[PSCustomObject]@{Data=$_.FullName;MQL5=$mq;Install=$ip}}};return @($inst)
}
function ChooseTarget($inst){
  if($inst.Count-eq0){throw 'No MT5 data folder found.'};$cfg=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5\config.json';if(Test-Path $cfg){try{$c=Get-Content $cfg -Raw|ConvertFrom-Json;$saved=[string]$c.target_data_folder;foreach($x in $inst){if($x.Data-eq$saved){return $x}}}catch{}}
  if($inst.Count-eq1){return $inst[0]};Write-Host 'Choose the MT5 instance:' -ForegroundColor Yellow;for($i=0;$i-lt$inst.Count;$i++){Write-Host " [$($i+1)] $($inst[$i].Data)"};do{$x=Read-Host 'Number';$n=0;$ok=[int]::TryParse($x,[ref]$n)}until($ok-and$n-ge1-and$n-le$inst.Count);return $inst[$n-1]
}
function FindMetaEditor($T){$c=@();if($T.Install){$b=$T.Install;if(Test-Path $b -PathType Leaf){$b=Split-Path -Parent $b};$c+=Join-Path $b 'metaeditor64.exe';$c+=Join-Path $b 'MetaEditor64.exe';$c+=Join-Path $b 'metaeditor.exe'};foreach($r in @($env:ProgramFiles,${env:ProgramFiles(x86)})){if($r){$c+=Join-Path $r 'MetaTrader 5\metaeditor64.exe';$c+=Join-Path $r 'MetaTrader 5\MetaEditor64.exe'}};foreach($p in $c){if($p-and(Test-Path $p)){return $p}};return $null}

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' Trade Zone - NATIVE SNIPER PARITY VALIDATOR' -ForegroundColor Cyan
Write-Host ' Validation only. Stable DataBridge/Sequence are NOT replaced.' -ForegroundColor Yellow
Write-Host '============================================================' -ForegroundColor Cyan

$tmp=Join-Path $env:TEMP ('TZParity_'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -Force -Path $tmp|Out-Null
try{
  $t=ChooseTarget (DiscoverTargets);$meta=FindMetaEditor $t;if(!$meta){throw 'MetaEditor not found.'}
  $incDir=Join-Path $t.MQL5 'Include\TradeZoneValidation';$scriptDir=Join-Path $t.MQL5 'Scripts\TradeZoneValidation';New-Item -ItemType Directory -Force -Path $incDir,$scriptDir|Out-Null
  $inc=Join-Path $incDir 'SniperContractParityV1.mqh';$src=Join-Path $scriptDir 'SniperContractParityVectorTest.mq5'
  Download "$Raw/mt5/include/SniperContractParityV1.mqh" $inc
  Download "$Raw/mt5/tests/SniperContractParityVectorTest.mq5" (Join-Path $tmp 'test.mq5')
  $test=Get-Content (Join-Path $tmp 'test.mq5') -Raw
  $test=$test.Replace('#include "../include/SniperContractParityV1.mqh"','#include <TradeZoneValidation/SniperContractParityV1.mqh>')
  Set-Content $src -Value $test -Encoding UTF8
  $log=Join-Path $tmp 'compile.log';$ex5=[IO.Path]::ChangeExtension($src,'.ex5');Remove-Item $ex5,$log -Force -ErrorAction SilentlyContinue
  Write-Host "Compiling native parity harness..." -ForegroundColor Cyan
  Start-Process -FilePath $meta -ArgumentList @("/compile:$src","/log:$log") -Wait|Out-Null;Start-Sleep -Milliseconds 900
  $txt=if(Test-Path $log){Get-Content $log -Raw}else{''}
  if(!(Test-Path $ex5)-or($txt-and$txt-notmatch'0 errors,\s*0 warnings')){if($txt){Write-Host $txt -ForegroundColor DarkYellow};throw 'Native parity harness compilation failed.'}
  Write-Host 'PASS: native parity harness compiled with 0 errors, 0 warnings.' -ForegroundColor Green
  Write-Host ''
  Write-Host 'NEXT:' -ForegroundColor Cyan
  Write-Host '  1. Open MT5 and right-click Navigator > Refresh.'
  Write-Host '  2. Open Scripts > TradeZoneValidation.'
  Write-Host '  3. Run SniperContractParityVectorTest on any chart.'
  Write-Host '  4. Open Toolbox > Experts and send a screenshot of the SNIPER_PARITY_VECTOR lines.'
  Write-Host ''
  Write-Host 'Your stable TradeZone EAs were not replaced.' -ForegroundColor Green
  PauseExit 0
}catch{Write-Host '';Write-Host "VALIDATION SETUP FAILED: $($_.Exception.Message)" -ForegroundColor Red;Write-Host 'Stable TradeZone EAs were not replaced.' -ForegroundColor Yellow;PauseExit 1}
finally{Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue}
