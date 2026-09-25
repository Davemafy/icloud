$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle='Trade Zone - Master Sniper History Exporter Compiler'

$Repo='Davemafy/icloud'
$Branch='master-sniper-backtest-v659'
$Raw="https://raw.githubusercontent.com/$Repo/$Branch"

function PauseExit([int]$Code=0){Write-Host '';Read-Host 'Press ENTER to close';exit $Code}
function Download([string]$Url,[string]$Out){
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 60
  if(!(Test-Path $Out)){throw "Download failed: $Url"}
  Unblock-File -LiteralPath $Out -ErrorAction SilentlyContinue
}
function DiscoverTargets(){
  $root=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
  if(!(Test-Path $root)){throw 'MT5 terminal data root not found.'}
  $inst=@()
  Get-ChildItem $root -Directory|ForEach-Object{
    $mq=Join-Path $_.FullName 'MQL5'
    if(Test-Path $mq){
      $or=Join-Path $_.FullName 'origin.txt';$ip=$null
      if(Test-Path $or){try{$ip=(Get-Content $or -Raw).Trim()}catch{}}
      $inst+=[PSCustomObject]@{Data=$_.FullName;MQL5=$mq;Install=$ip}
    }
  }
  return @($inst)
}
function ChooseTarget($inst){
  if($inst.Count-eq0){throw 'No MT5 data folder found.'}
  $cfg=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5\config.json'
  if(Test-Path $cfg){
    try{
      $c=Get-Content $cfg -Raw|ConvertFrom-Json
      $saved=[string]$c.target_data_folder
      foreach($x in $inst){if($x.Data-eq$saved){return $x}}
    }catch{}
  }
  if($inst.Count-eq1){return $inst[0]}
  Write-Host 'Choose the MT5 instance:' -ForegroundColor Yellow
  for($i=0;$i-lt$inst.Count;$i++){Write-Host " [$($i+1)] $($inst[$i].Data)"}
  do{$x=Read-Host 'Number';$n=0;$ok=[int]::TryParse($x,[ref]$n)}until($ok-and$n-ge1-and$n-le$inst.Count)
  return $inst[$n-1]
}
function FindMetaEditor($T){
  $c=@()
  if($T.Install){
    $b=$T.Install
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

Write-Host '================================================================' -ForegroundColor Cyan
Write-Host ' Trade Zone - MASTER SNIPER HISTORY EXPORTER COMPILER' -ForegroundColor Cyan
Write-Host ' Validation only. No EA is replaced or attached.' -ForegroundColor Yellow
Write-Host '================================================================' -ForegroundColor Cyan

try{
  $t=ChooseTarget (DiscoverTargets)
  $meta=FindMetaEditor $t
  if(!$meta){throw 'MetaEditor not found.'}

  $dest=Join-Path $t.MQL5 'Scripts\TradeZoneValidation'
  New-Item -ItemType Directory -Force -Path $dest|Out-Null
  $src=Join-Path $dest 'TradeZone_MasterSniper_HistoryExporter.mq5'
  Download "$Raw/mt5/backtest/TradeZone_MasterSniper_HistoryExporter.mq5" $src

  $log=Join-Path $dest 'MasterSniper_HistoryExporter_compile.log'
  $ex5=[IO.Path]::ChangeExtension($src,'.ex5')
  Remove-Item $log,$ex5 -Force -ErrorAction SilentlyContinue

  Write-Host 'Compiling no-trading historical data exporter...' -ForegroundColor Cyan
  Start-Process -FilePath $meta -ArgumentList @("/compile:$src","/log:$log") -Wait|Out-Null
  Start-Sleep -Milliseconds 900

  $txt=if(Test-Path $log){Get-Content $log -Raw}else{''}
  if(!(Test-Path $ex5)-or($txt-and$txt-notmatch'0 errors,\s*0 warnings')){
    if($txt){Write-Host '';Write-Host $txt -ForegroundColor DarkYellow}
    throw 'History exporter compilation failed.'
  }

  Write-Host ''
  Write-Host 'PASS: MASTER SNIPER HISTORY EXPORTER COMPILED CLEANLY.' -ForegroundColor Green
  Write-Host '  Contract: MASTER_SNIPER_V659_HISTORY_EXPORT_V1' -ForegroundColor Green
  Write-Host '  0 errors, 0 warnings.' -ForegroundColor Green
  Write-Host ''
  Write-Host 'No live EA was replaced or attached.' -ForegroundColor Green
  Write-Host 'The exporter is under Navigator > Scripts > TradeZoneValidation.' -ForegroundColor Cyan
  Write-Host 'Send a screenshot of this window back to ChatGPT.' -ForegroundColor Cyan
  PauseExit 0
}catch{
  Write-Host ''
  Write-Host "HISTORY EXPORTER VALIDATION FAILED: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host 'Live EAs were not changed.' -ForegroundColor Yellow
  PauseExit 1
}
