$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle='Trade Zone - Sniper Runtime Parity Probe Installer'

$Repo='Davemafy/icloud'
$Branch='sniper-contract-parity-v1'
$Raw="https://raw.githubusercontent.com/$Repo/$Branch"

function PauseExit([int]$Code=0){Write-Host '';Read-Host 'Press ENTER to close';exit $Code}
function Download([string]$Url,[string]$Out){
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 60
  if(!(Test-Path $Out)){throw "Download failed: $Url"}
  Unblock-File -LiteralPath $Out -ErrorAction SilentlyContinue
}
function FindMetaEditor([string]$Install){
  $c=@()
  if($Install){
    $b=$Install
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
  foreach($p in $c){if($p-and(Test-Path $p)){return $p}}
  return $null
}
function MqlEscape([string]$s){
  if($null-eq$s){return ''}
  return $s.Replace('\','\\').Replace('"','\"')
}

Write-Host '================================================================' -ForegroundColor Cyan
Write-Host ' Trade Zone - MASTER SNIPER RUNTIME PARITY PROBE' -ForegroundColor Cyan
Write-Host ' Installs a NO-TRADING diagnostic Script only.' -ForegroundColor Yellow
Write-Host ' Working DataBridge / Sequence EAs are NOT replaced or attached.' -ForegroundColor Yellow
Write-Host '================================================================' -ForegroundColor Cyan

try{
  $cfgPath=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5\config.json'
  if(!(Test-Path $cfgPath)){throw "Managed Trade Zone config not found: $cfgPath"}
  $cfg=Get-Content $cfgPath -Raw|ConvertFrom-Json
  $data=[string]$cfg.target_data_folder
  $install=[string]$cfg.mt5_install_path
  $cloudUrl=[string]$cfg.cloud_url
  $cloudKey=[string]$cfg.cloud_api_key

  if([string]::IsNullOrWhiteSpace($data)-or!(Test-Path $data)){throw 'Configured MT5 data folder is unavailable.'}
  if([string]::IsNullOrWhiteSpace($cloudUrl)-or[string]::IsNullOrWhiteSpace($cloudKey)){throw 'Managed cloud URL/key are missing.'}

  $mql5=Join-Path $data 'MQL5'
  $core=Join-Path $mql5 'Include\TradeZoneCore'
  New-Item -ItemType Directory -Force -Path $core|Out-Null
  Download "$Raw/mt5/stable/SniperContractParityV1.mqh" (Join-Path $core 'SniperContractParityV1.mqh')

  $dest=Join-Path $mql5 'Scripts\TradeZoneValidation'
  New-Item -ItemType Directory -Force -Path $dest|Out-Null
  $template=Join-Path $env:TEMP 'SniperContractParityRuntimeProbe.template.mq5'
  $src=Join-Path $dest 'SniperContractParityRuntimeProbe.mq5'
  Download "$Raw/mt5/tests/SniperContractParityRuntimeProbe.mq5" $template

  $text=Get-Content $template -Raw
  $text=$text.Replace('__CLOUD_BASE_URL__',(MqlEscape $cloudUrl))
  $text=$text.Replace('__CLOUD_API_KEY__',(MqlEscape $cloudKey))
  [IO.File]::WriteAllText($src,$text,[Text.UTF8Encoding]::new($false))
  Remove-Item $template -Force -ErrorAction SilentlyContinue

  $meta=FindMetaEditor $install
  if(!$meta){throw 'MetaEditor not found.'}
  $log=Join-Path $dest 'SniperContractParityRuntimeProbe_compile.log'
  $ex5=[IO.Path]::ChangeExtension($src,'.ex5')
  Remove-Item $log,$ex5 -Force -ErrorAction SilentlyContinue
  Write-Host 'Compiling NO-TRADING runtime probe...' -ForegroundColor Cyan
  Start-Process -FilePath $meta -ArgumentList @("/compile:$src","/log:$log") -Wait|Out-Null
  Start-Sleep -Milliseconds 900
  $logText=if(Test-Path $log){Get-Content $log -Raw}else{''}
  if(!(Test-Path $ex5)-or($logText-and$logText-notmatch'0 errors,\s*0 warnings')){
    if($logText){Write-Host $logText -ForegroundColor DarkYellow}
    throw 'Runtime parity probe compilation failed.'
  }

  Write-Host ''
  Write-Host 'PASS: runtime parity probe compiled with 0 errors, 0 warnings.' -ForegroundColor Green
  Write-Host 'No trading EA was replaced or attached.' -ForegroundColor Green
  Write-Host ''
  Write-Host 'NOW IN MT5:' -ForegroundColor Cyan
  Write-Host '  1. Navigator > Scripts > right-click Refresh.' -ForegroundColor White
  Write-Host '  2. Open TradeZoneValidation.' -ForegroundColor White
  Write-Host '  3. Double-click SniperContractParityRuntimeProbe on XAUUSD.' -ForegroundColor White
  Write-Host '  4. It runs ONCE and NEVER sends an order.' -ForegroundColor White
  Write-Host '  5. Open Toolbox > Experts and send ChatGPT the SNIPER_PARITY_RUNTIME lines.' -ForegroundColor White
  Write-Host ''
  Write-Host 'Expected final line: SNIPER_PARITY_RUNTIME PASS OVERALL' -ForegroundColor Green
  PauseExit 0
}catch{
  Write-Host ''
  Write-Host "RUNTIME PROBE PREPARATION FAILED: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host 'Working EAs were not changed.' -ForegroundColor Yellow
  PauseExit 1
}
