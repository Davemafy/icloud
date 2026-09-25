$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle='Trade Zone - Sniper 3.42/1.51 Candidate Compiler'

$Repo='Davemafy/icloud'
$Branch='sniper-contract-parity-v1'
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
function CompileOne([string]$Meta,[string]$Src,[string]$LogDir){
  $name=[IO.Path]::GetFileNameWithoutExtension($Src)
  $ex5=[IO.Path]::ChangeExtension($Src,'.ex5')
  $log=Join-Path $LogDir ($name+'_compile.log')
  Remove-Item $ex5,$log -Force -ErrorAction SilentlyContinue
  Write-Host "Compiling: $(Split-Path $Src -Leaf)" -ForegroundColor Cyan
  Start-Process -FilePath $Meta -ArgumentList @("/compile:$Src","/log:$log") -Wait|Out-Null
  Start-Sleep -Milliseconds 900
  $txt=if(Test-Path $log){Get-Content $log -Raw}else{''}
  if(!(Test-Path $ex5)-or($txt-and$txt-notmatch'0 errors,\s*0 warnings')){
    if($txt){Write-Host '';Write-Host $txt -ForegroundColor DarkYellow}
    throw "Compilation failed for $(Split-Path $Src -Leaf)."
  }
  Write-Host '  PASS: 0 errors, 0 warnings.' -ForegroundColor Green
}

Write-Host '================================================================' -ForegroundColor Cyan
Write-Host ' Trade Zone - SNIPER 3.42 / BRIDGE 1.51 CANDIDATE COMPILER' -ForegroundColor Cyan
Write-Host ' Compile validation only. Working 3.41 / 1.50 EAs are NOT replaced.' -ForegroundColor Yellow
Write-Host '================================================================' -ForegroundColor Cyan

try{
  $t=ChooseTarget (DiscoverTargets)
  $meta=FindMetaEditor $t
  if(!$meta){throw 'MetaEditor not found.'}

  $core=Join-Path $t.MQL5 'Include\TradeZoneCore'
  $required=@(
    (Join-Path $core 'InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5'),
    (Join-Path $core 'InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5'),
    (Join-Path $core 'TradeZone_ZoneRenderer_v1_0.mqh')
  )
  foreach($p in $required){if(!(Test-Path $p)){throw "Required stable support file missing: $p"}}

  New-Item -ItemType Directory -Force -Path $core|Out-Null
  $parity=Join-Path $core 'SniperContractParityV1.mqh'
  Download "$Raw/mt5/stable/SniperContractParityV1.mqh" $parity

  $dest=Join-Path $t.MQL5 'Experts\TradeZoneValidation'
  New-Item -ItemType Directory -Force -Path $dest|Out-Null
  $seq=Join-Path $dest 'InstitutionalSMC_SequenceEA_v3_42_SniperContractParity_Demo.mq5'
  $bridge=Join-Path $dest 'InstitutionalSMC_DataBridge_v1_51_SniperContractParity.mq5'
  Download "$Raw/mt5/stable/InstitutionalSMC_SequenceEA_v3_42_SniperContractParity_Demo.mq5" $seq
  Download "$Raw/mt5/stable/InstitutionalSMC_DataBridge_v1_51_SniperContractParity.mq5" $bridge

  CompileOne $meta $bridge $dest
  CompileOne $meta $seq $dest

  Write-Host ''
  Write-Host 'PASS: BOTH PARITY CANDIDATES COMPILE CLEANLY.' -ForegroundColor Green
  Write-Host '  DataBridge v1.51 candidate: 0 errors, 0 warnings.' -ForegroundColor Green
  Write-Host '  Sequence EA v3.42 candidate: 0 errors, 0 warnings.' -ForegroundColor Green
  Write-Host ''
  Write-Host 'No working EA was replaced or attached.' -ForegroundColor Green
  Write-Host 'Send a screenshot of this window back to ChatGPT.' -ForegroundColor Cyan
  PauseExit 0
}catch{
  Write-Host ''
  Write-Host "CANDIDATE VALIDATION FAILED: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host 'Working 3.41 / 1.50 EAs were not replaced.' -ForegroundColor Yellow
  PauseExit 1
}
