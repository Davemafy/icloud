$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle='Trade Zone - Master Sniper Backtest Lab'

$Repo='Davemafy/icloud'
$Branch='main'
$Raw="https://raw.githubusercontent.com/$Repo/$Branch"
$ExporterRel='mt5/backtest/TradeZone_MasterSniper_HistoryExporter.mq5'
$BacktestRel='mt5/backtest/InstitutionalSMC_SequenceEA_v3_42_MasterSniper_Backtest_Demo.mq5'

function PauseExit([int]$Code=0){Write-Host '';Read-Host 'Press ENTER to close';exit $Code}
function Download([string]$Url,[string]$Out){
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 90
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
  $pf=[Environment]::GetFolderPath('ProgramFiles')
  $pf86=[Environment]::GetFolderPath('ProgramFilesX86')
  foreach($r in @($pf,$pf86)){
    if($r){
      $c+=Join-Path $r 'MetaTrader 5\metaeditor64.exe'
      $c+=Join-Path $r 'MetaTrader 5\MetaEditor64.exe'
    }
  }
  foreach($p in $c){if($p-and(Test-Path $p)){return $p}}
  return $null
}
function FindTerminal([string]$Install){
  if(!$Install){return $null}
  $b=$Install
  if(Test-Path $b -PathType Leaf){
    if((Split-Path $b -Leaf)-match '^terminal'){return $b}
    $b=Split-Path -Parent $b
  }
  foreach($name in @('terminal64.exe','terminal.exe')){
    $p=Join-Path $b $name
    if(Test-Path $p){return $p}
  }
  return $null
}
function CompileOne([string]$Meta,[string]$Src,[string]$Log){
  $ex5=[IO.Path]::ChangeExtension($Src,'.ex5')
  Remove-Item $ex5,$Log -Force -ErrorAction SilentlyContinue
  Write-Host "Compiling $(Split-Path $Src -Leaf)..." -ForegroundColor Cyan
  Start-Process -FilePath $Meta -ArgumentList @("/compile:$Src","/log:$Log") -Wait|Out-Null
  Start-Sleep -Milliseconds 900
  $txt=if(Test-Path $Log){Get-Content $Log -Raw}else{''}
  if(!(Test-Path $ex5)-or($txt-and$txt-notmatch'0 errors,\s*0 warnings')){
    if($txt){Write-Host '';Write-Host $txt -ForegroundColor DarkYellow}
    throw "Compilation failed: $(Split-Path $Src -Leaf)"
  }
  Write-Host '  PASS: 0 errors, 0 warnings.' -ForegroundColor Green
}
function ReadDate([string]$Prompt,[string]$Default){
  $raw=Read-Host "$Prompt [$Default]"
  if([string]::IsNullOrWhiteSpace($raw)){$raw=$Default}
  $dt=[datetime]::MinValue
  if(![datetime]::TryParseExact($raw,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::None,[ref]$dt)){
    throw "Invalid date '$raw'. Use YYYY-MM-DD."
  }
  return $dt
}
function EscapeMql([string]$s){return $s.Replace('\','\\').Replace('"','\"')}

Write-Host '================================================================' -ForegroundColor Cyan
Write-Host ' Trade Zone - MASTER SNIPER BACKTEST LAB' -ForegroundColor Cyan
Write-Host ' One guided workflow: compile -> export -> replay -> tester package' -ForegroundColor Cyan
Write-Host ' LIVE 6.3.32 EAs ARE NOT REPLACED OR ATTACHED.' -ForegroundColor Yellow
Write-Host '================================================================' -ForegroundColor Cyan
Write-Host ''

$tmp=$null
try{
  $cfgPath=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5\config.json'
  if(!(Test-Path $cfgPath)){throw "Managed Trade Zone config not found: $cfgPath"}
  $cfg=Get-Content $cfgPath -Raw|ConvertFrom-Json
  $data=[string]$cfg.target_data_folder
  $install=[string]$cfg.mt5_install_path
  $cloud=[string]$cfg.cloud_url
  $apiKey=[string]$cfg.cloud_api_key
  if([string]::IsNullOrWhiteSpace($data)-or!(Test-Path $data)){throw 'Configured MT5 data folder is unavailable.'}
  if([string]::IsNullOrWhiteSpace($cloud)-or[string]::IsNullOrWhiteSpace($apiKey)){throw 'Managed Cloud URL/key are missing.'}

  $start=ReadDate 'Backtest start date' '2026-06-01'
  $end=ReadDate 'Backtest end date' '2026-08-31'
  if($end -lt $start){throw 'End date must be on or after start date.'}
  if((New-TimeSpan -Start $start -End $end).TotalDays -gt 120){throw 'First-pass lab is limited to 120 days per run.'}

  $xau=Read-Host 'Gold symbol in this MT5 [XAUUSD]'
  if([string]::IsNullOrWhiteSpace($xau)){$xau='XAUUSD'}
  $dxy=Read-Host 'DXY symbol in this MT5 [DXYUSD]'
  if([string]::IsNullOrWhiteSpace($dxy)){$dxy='DXYUSD'}
  $spreadRaw=Read-Host 'Cloud replay spread in points [16]'
  if([string]::IsNullOrWhiteSpace($spreadRaw)){$spreadRaw='16'}
  $spread=0.0
  if(![double]::TryParse($spreadRaw,[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$spread)-or$spread-le0){throw 'Invalid spread.'}

  $mql5=Join-Path $data 'MQL5'
  $meta=FindMetaEditor $install
  if(!$meta){throw 'MetaEditor not found.'}

  $expertDir=Join-Path $mql5 'Experts\TradeZoneValidation'
  $scriptDir=Join-Path $mql5 'Scripts\TradeZoneValidation'
  New-Item -ItemType Directory -Force -Path $expertDir,$scriptDir|Out-Null

  $tmp=Join-Path $env:TEMP ('TZ_BacktestLab_'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tmp|Out-Null

  $exportTemplate=Join-Path $tmp 'HistoryExporter.template.mq5'
  $exportSrc=Join-Path $scriptDir 'TradeZone_MasterSniper_HistoryExporter.mq5'
  $backtestSrc=Join-Path $expertDir 'InstitutionalSMC_SequenceEA_v3_42_MasterSniper_Backtest_Demo.mq5'
  Download "$Raw/$ExporterRel" $exportTemplate
  Download "$Raw/$BacktestRel" $backtestSrc

  $source=Get-Content $exportTemplate -Raw
  $source=$source.Replace('input string XauSymbol="XAUUSD";','input string XauSymbol="'+(EscapeMql $xau)+'";')
  $source=$source.Replace('input string DxySymbol="DXYUSD";','input string DxySymbol="'+(EscapeMql $dxy)+'";')
  $source=$source.Replace("input datetime TestStart=D'2026.06.01 00:00';","input datetime TestStart=D'"+$start.ToString('yyyy.MM.dd')+" 00:00';")
  $source=$source.Replace("input datetime TestEnd=D'2026.08.31 23:59';","input datetime TestEnd=D'"+$end.ToString('yyyy.MM.dd')+" 23:59';")
  [IO.File]::WriteAllText($exportSrc,$source,[Text.UTF8Encoding]::new($false))

  CompileOne $meta $exportSrc (Join-Path $tmp 'history_exporter_compile.log')
  CompileOne $meta $backtestSrc (Join-Path $tmp 'backtest_ea_compile.log')

  $common=Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files'
  $exportDir=Join-Path $common 'TradeZoneBacktest\MasterSniperV659'
  if(Test-Path $exportDir){Remove-Item $exportDir -Recurse -Force}
  New-Item -ItemType Directory -Force -Path $exportDir|Out-Null

  Write-Host ''
  Write-Host 'ONE ACTION INSIDE MT5:' -ForegroundColor Yellow
  Write-Host '  Navigator > Scripts > right-click Refresh.' -ForegroundColor White
  Write-Host '  Open TradeZoneValidation.' -ForegroundColor White
  Write-Host '  Double-click TradeZone_MasterSniper_HistoryExporter on any chart.' -ForegroundColor White
  Write-Host '  Leave the prepared inputs unchanged and click OK.' -ForegroundColor White
  Write-Host ''
  Write-Host 'This window will detect the export and continue automatically.' -ForegroundColor Cyan
  Write-Host 'Waiting up to 30 minutes for historical synchronization/export...' -ForegroundColor Cyan

  $manifest=Join-Path $exportDir 'export_manifest.txt'
  $deadline=(Get-Date).AddMinutes(30)
  while(!(Test-Path $manifest)){
    if((Get-Date)-gt$deadline){throw 'Timed out waiting for MT5 history export.'}
    Start-Sleep -Seconds 3
  }
  Start-Sleep -Seconds 2

  $required=@('XAU_D1.csv','XAU_H4.csv','XAU_H1.csv','XAU_M15.csv','XAU_M1.csv','DXY_D1.csv','DXY_H4.csv','DXY_H1.csv')
  foreach($name in $required){
    $p=Join-Path $exportDir $name
    if(!(Test-Path $p)-or(Get-Item $p).Length-lt50){throw "Historical export incomplete: $name"}
  }
  if(!(Test-Path (Join-Path $exportDir 'news.csv'))){
    Set-Content (Join-Path $exportDir 'news.csv') -Value 'ts,currency,title,impact' -Encoding ASCII
  }
  Write-Host 'PASS: required XAU/DXY history files exported.' -ForegroundColor Green

  $upload=Join-Path $tmp 'history.zip'
  Compress-Archive -Path (Join-Path $exportDir '*') -DestinationPath $upload -CompressionLevel Optimal -Force

  $manifestKv=@{}
  Get-Content $manifest | ForEach-Object {
    if($_ -match '='){
      $parts=$_.Split('=',2)
      $manifestKv[$parts[0].Trim()]=$parts[1].Trim()
    }
  }
  $startEpoch=[long]$manifestKv['test_start']
  $endEpoch=[long]$manifestKv['test_end']
  if($startEpoch-le0-or$endEpoch-le$startEpoch){throw 'History exporter manifest contains invalid replay epochs.'}
  $minimumRows=@{
    'XAU_D1.csv_rows'=80;
    'XAU_H4.csv_rows'=120;
    'XAU_H1.csv_rows'=160;
    'XAU_M15.csv_rows'=160;
    'DXY_D1.csv_rows'=60;
    'DXY_H4.csv_rows'=80;
    'DXY_H1.csv_rows'=100
  }
  foreach($key in $minimumRows.Keys){
    $actual=[int]$manifestKv[$key]
    if($actual-lt[int]$minimumRows[$key]){
      throw "Insufficient warm-up history: $key has $actual rows, needs at least $($minimumRows[$key])."
    }
  }
  $newsRows=[int]$manifestKv['news_rows']
  if((New-TimeSpan -Start $start -End $end).TotalDays -gt 7 -and $newsRows -le 0){
    throw 'USD economic-calendar history is empty; full Master Sniper prompt replay cannot be certified.'
  }
  Write-Host "PASS: history warm-up contract complete; USD news rows=$newsRows." -ForegroundColor Green
  $startIso=[DateTimeOffset]::FromUnixTimeSeconds($startEpoch).UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ss+00:00')
  $endIso=[DateTimeOffset]::FromUnixTimeSeconds($endEpoch).UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ss+00:00')
  $tz=[uri]::EscapeDataString('Africa/Lagos')
  $spreadText=$spread.ToString([Globalization.CultureInfo]::InvariantCulture)
  $baseJobUri=$cloud.TrimEnd('/')+"/validation/backtest/v659/jobs"
  $startUri=$baseJobUri+"?start="+[uri]::EscapeDataString($startIso)+"&end="+[uri]::EscapeDataString($endIso)+"&timezone_name=$tz&spread_points=$spreadText&point=0.01"
  $resultZip=Join-Path $tmp 'master_sniper_backtest_package.zip'

  Write-Host ''
  Write-Host 'Starting Master Sniper 6.5.90 isolated Cloud replay job...' -ForegroundColor Cyan
  $startResponse=Invoke-RestMethod -Method POST -Uri $startUri -Headers @{'X-API-Key'=$apiKey} -ContentType 'application/zip' -InFile $upload -TimeoutSec 120
  $jobId=[string]$startResponse.job_id
  if([string]::IsNullOrWhiteSpace($jobId)){throw 'Cloud did not return a backtest job ID.'}
  Write-Host "Cloud replay job: $jobId" -ForegroundColor Cyan

  $statusUri=$baseJobUri+"/"+$jobId
  $downloadUri=$statusUri+"/download"
  $jobDeadline=(Get-Date).AddMinutes(35)
  $lastStatus=''
  while($true){
    if((Get-Date)-gt$jobDeadline){throw 'Cloud replay job exceeded the 35-minute lab limit.'}
    Start-Sleep -Seconds 5
    $job=Invoke-RestMethod -Method GET -Uri $statusUri -Headers @{'X-API-Key'=$apiKey} -TimeoutSec 60
    $state=[string]$job.status
    if($state-ne$lastStatus){
      Write-Host "Cloud replay status: $state" -ForegroundColor Cyan
      $lastStatus=$state
    }
    if($state-eq'COMPLETED'){break}
    if($state-eq'FAILED'){throw ("Cloud replay failed: "+[string]$job.error)}
    if($state-notin @('QUEUED','RUNNING')){throw "Unexpected Cloud replay status: $state"}
  }

  Invoke-WebRequest -UseBasicParsing -Method GET -Uri $downloadUri -Headers @{'X-API-Key'=$apiKey} -OutFile $resultZip -TimeoutSec 120
  if(!(Test-Path $resultZip)-or(Get-Item $resultZip).Length-lt100){throw 'Cloud replay completed but returned no usable package.'}

  $resultDir=Join-Path $exportDir 'ReplayResult'
  if(Test-Path $resultDir){Remove-Item $resultDir -Recurse -Force}
  New-Item -ItemType Directory -Force -Path $resultDir|Out-Null
  Expand-Archive -Path $resultZip -DestinationPath $resultDir -Force

  foreach($name in @('SMC_v6_tester_plans.csv','SMC_v659_tester_plans_contract.csv')){
    $p=Join-Path $resultDir $name
    if(!(Test-Path $p)-or(Get-Item $p).Length-lt20){throw "Replay output missing: $name"}
    Copy-Item $p (Join-Path $common $name) -Force
  }

  $metadata=Join-Path $resultDir 'SMC_v659_tester_plans_metadata.json'
  if(!(Test-Path $metadata)){throw 'Replay metadata missing.'}
  $metaObj=Get-Content $metadata -Raw|ConvertFrom-Json
  if([string]$metaObj.contract-ne'MASTER_SNIPER_V659_NO_LOOKAHEAD_REPLAY_V1'-or-not[bool]$metaObj.no_lookahead){
    throw 'Replay metadata did not certify the no-lookahead contract.'
  }

  $next=Join-Path $resultDir 'README_NEXT.txt'
  $desktop=[Environment]::GetFolderPath('Desktop')
  Copy-Item $next (Join-Path $desktop 'MasterSniper_Backtest_NEXT.txt') -Force

  $terminal=FindTerminal $install
  $collector=Join-Path $desktop 'Collect_MasterSniper_Backtest_Results.bat'
  $nl=[Environment]::NewLine
  $commonRoot=$common
  $resultMeta=Join-Path $resultDir 'SMC_v659_tester_plans_metadata.json'
  $collectorText='@echo off'+$nl+
    'setlocal'+$nl+
    'set "OUT=%USERPROFILE%\Desktop\MasterSniper_Backtest_Result"'+$nl+
    'if exist "%OUT%" rmdir /s /q "%OUT%"'+$nl+
    'mkdir "%OUT%"'+$nl+
    'copy /y "'+$commonRoot+'\MasterSniper_v659_tester_journal.csv" "%OUT%\" >nul'+$nl+
    'copy /y "'+$commonRoot+'\MasterSniper_v659_tester_summary.txt" "%OUT%\" >nul'+$nl+
    'copy /y "'+$resultMeta+'" "%OUT%\" >nul'+$nl+
    'copy /y "'+(Join-Path $resultDir 'MasterSniper_Backtest_Job.json')+'" "%OUT%\" >nul'+$nl+
    'powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path ''%OUT%\*'' -DestinationPath ''%USERPROFILE%\Desktop\MasterSniper_Backtest_Result.zip'' -Force"'+$nl+
    'echo.'+$nl+
    'echo DONE: MasterSniper_Backtest_Result.zip is on the Desktop.'+$nl+
    'pause'+$nl
  [IO.File]::WriteAllText($collector,$collectorText,[Text.ASCIIEncoding]::new())

  if($terminal){
    $ini=Join-Path $desktop 'MasterSniper_Backtest_RealTicks.ini'
    $expert='TradeZoneValidation\InstitutionalSMC_SequenceEA_v3_42_MasterSniper_Backtest_Demo'
    $iniLines=@(
      '[Tester]',
      "Expert=$expert",
      "Symbol=$xau",
      'Period=M1',
      'Model=4',
      'ExecutionMode=0',
      'Optimization=0',
      "FromDate=$($start.ToString('yyyy.MM.dd'))",
      "ToDate=$($end.ToString('yyyy.MM.dd'))",
      'ForwardMode=0',
      'Deposit=10000',
      'Currency=USD',
      'Leverage=1:100',
      'UseLocal=1',
      'UseRemote=0',
      'UseCloud=0',
      'Visual=0',
      'ShutdownTerminal=0'
    )
    [IO.File]::WriteAllLines($ini,$iniLines,[Text.UTF8Encoding]::new($false))

    $launcher=Join-Path $desktop 'Run_MasterSniper_Backtest_When_MT5_Closed.bat'
    $nl=[Environment]::NewLine
    $launcherText='@echo off'+$nl+
      'echo This launcher uses Every tick based on real ticks (Model=4).'+$nl+
      'echo Close the normal MT5 terminal first so its live paper charts are not interrupted.'+$nl+
      'pause'+$nl+
      'start "" "'+$terminal+'" /config:"'+$ini+'"'+$nl
    [IO.File]::WriteAllText($launcher,$launcherText,[Text.ASCIIEncoding]::new())
  }

  Write-Host ''
  Write-Host '============================================================' -ForegroundColor Green
  Write-Host ' MASTER SNIPER BACKTEST PACKAGE READY' -ForegroundColor Green
  Write-Host '============================================================' -ForegroundColor Green
  Write-Host "Replay contract: $($metaObj.contract)" -ForegroundColor Green
  Write-Host "Cloud version: $($metaObj.cloud_version)" -ForegroundColor Green
  Write-Host "Sequence contract: $($metaObj.sequence_contract)" -ForegroundColor Green
  Write-Host "Plan states: $($metaObj.plan_rows)" -ForegroundColor Green
  Write-Host 'No-lookahead: CERTIFIED' -ForegroundColor Green
  Write-Host ''
  Write-Host 'Tester files are already in MT5 Common Files.' -ForegroundColor Cyan
  Write-Host 'Backtest EA is already compiled under Experts > TradeZoneValidation.' -ForegroundColor Cyan
  Write-Host 'A real-tick tester launcher, NEXT instructions, and result collector were placed on the Desktop.' -ForegroundColor Cyan
  Write-Host ''
  Write-Host 'Live DataBridge 1.51 / Sequence 3.42 were never replaced or detached.' -ForegroundColor Yellow
  PauseExit 0
}catch{
  Write-Host ''
  Write-Host "BACKTEST LAB FAILED: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host 'Live EAs were not replaced or detached.' -ForegroundColor Yellow
  PauseExit 1
}finally{
  if($tmp-and(Test-Path $tmp)){Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue}
}
