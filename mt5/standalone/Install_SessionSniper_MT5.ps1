param([switch]$SkipCompile)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$InstallerVersion='SESSION_SNIPER_INSTALLER_0.11'
$Host.UI.RawUI.WindowTitle='Trade Zone - Session Sniper Standalone Installer 0.11'

$Repo='Davemafy/icloud'
$Ref='66cc1934dae0ad4bb585f70c3e73262052649409'
$SourceName='SessionSniperEA_v0_11_7030Runner_Demo.mq5'
$SourceUrl="https://raw.githubusercontent.com/$Repo/$Ref/mt5/standalone/$SourceName"

function PauseExit([int]$Code=0){
  Write-Host ''
  Read-Host 'Press ENTER to close'
  exit $Code
}

function Download([string]$Url,[string]$Out){
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 60
  if(!(Test-Path $Out)){throw "Download failed: $Url"}
  Unblock-File -LiteralPath $Out -ErrorAction SilentlyContinue
}

function NormalizeMT5DataPath([string]$PathText){
  if([string]::IsNullOrWhiteSpace($PathText)){return ''}
  $p=$PathText.Trim().Trim('"').Trim("'")
  try{$p=[IO.Path]::GetFullPath($p)}catch{}
  return ($p -replace '[\\/]+$','').ToLowerInvariant()
}

function DiscoverTargets(){
  $root=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
  if(!(Test-Path $root)){throw 'MT5 terminal data root not found.'}
  $inst=@()
  Get-ChildItem $root -Directory | ForEach-Object {
    $mq=Join-Path $_.FullName 'MQL5'
    if(Test-Path $mq){
      $or=Join-Path $_.FullName 'origin.txt'
      $ip=$null
      if(Test-Path $or){try{$ip=(Get-Content $or -Raw).Trim()}catch{}}
      $inst+=[PSCustomObject]@{Data=$_.FullName;MQL5=$mq;Install=$ip}
    }
  }
  return @($inst)
}

function FindUniqueRunningMT5Target($targets){
  $running=@()
  try{
    $running=@(Get-CimInstance Win32_Process -Filter "Name = 'terminal64.exe' OR Name = 'terminal.exe'" -ErrorAction Stop)
  }catch{return $null}
  $matches=@()
  foreach($proc in @($running)){
    if([string]::IsNullOrWhiteSpace([string]$proc.ExecutablePath)){continue}
    if(([string]$proc.CommandLine) -match '(?i)(?:^|\s)[/-]portable(?:\s|$)'){continue}
    $liveInstall=NormalizeMT5DataPath (Split-Path -Parent ([string]$proc.ExecutablePath))
    if(!$liveInstall){continue}
    foreach($candidate in @($targets)){
      if([string]::IsNullOrWhiteSpace([string]$candidate.Install)){continue}
      $origin=[string]$candidate.Install
      if($origin -match '(?i)\\(?:terminal(?:64)?|metaeditor(?:64)?)\.exe$'){
        $origin=Split-Path -Parent $origin
      }
      if((NormalizeMT5DataPath $origin)-eq$liveInstall){
        $matches+=,[PSCustomObject]@{Target=$candidate;ProcessId=$proc.ProcessId}
      }
    }
  }
  if($matches.Count-ne1){return $null}
  return $matches[0].Target
}

function ChooseTarget($inst){
  $targets=@($inst)
  if($targets.Count-eq0){throw 'No MT5 data folder found.'}
  if($targets.Count-eq1){
    Write-Host "MT5 data folder: $($targets[0].Data)" -ForegroundColor Green
    return $targets[0]
  }

  $live=FindUniqueRunningMT5Target $targets
  if($null-ne$live){
    Write-Host "Auto-detected running MT5: $($live.Data)" -ForegroundColor Green
    return $live
  }

  while($true){
    Write-Host ''
    Write-Host 'Multiple MT5 data folders found:' -ForegroundColor Yellow
    for($i=0;$i-lt$targets.Count;$i++){
      Write-Host ("  [{0}] {1}" -f ($i+1),$targets[$i].Data)
    }
    Write-Host 'In the MT5 you use, click File > Open Data Folder.' -ForegroundColor Cyan
    $x=Read-Host 'Enter matching number'
    $n=0
    if([int]::TryParse($x,[ref]$n) -and $n-ge1 -and $n-le$targets.Count){
      return $targets[$n-1]
    }
    Write-Host 'Invalid selection.' -ForegroundColor Red
  }
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
      $c+=Join-Path $r 'MetaTrader 5\metaeditor.exe'
    }
  }
  foreach($p in $c){if($p -and (Test-Path $p)){return $p}}
  return $null
}

function CompileOne([string]$Meta,[string]$Src,[string]$LogDir){
  New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
  $ex5=[IO.Path]::ChangeExtension($Src,'.ex5')
  $name=[IO.Path]::GetFileNameWithoutExtension($Src)
  $log=Join-Path $LogDir ($name+'_'+[guid]::NewGuid().ToString('N')+'_compile.log')
  Remove-Item $ex5 -Force -ErrorAction SilentlyContinue

  Write-Host "Compiling $([IO.Path]::GetFileName($Src))..." -ForegroundColor Cyan
  $p=Start-Process -FilePath $Meta -ArgumentList @("/compile:$Src","/log:$log") -PassThru
  $p.WaitForExit()

  $txt=''
  $deadline=(Get-Date).AddSeconds(30)
  do{
    if(Test-Path $log){
      try{$txt=Get-Content $log -Raw -ErrorAction Stop}catch{$txt=''}
    }
    if((Test-Path $ex5) -and $txt -match '\d+ errors,\s*\d+ warnings'){break}
    Start-Sleep -Milliseconds 300
  }while((Get-Date)-lt$deadline)

  if(!(Test-Path $ex5)){
    if($txt){Write-Host $txt -ForegroundColor DarkYellow}
    throw 'MetaEditor did not produce the EX5. Existing Trade Zone files were not changed.'
  }
  if($txt -notmatch '0 errors,\s*0 warnings'){
    Write-Host $txt -ForegroundColor Yellow
    Remove-Item $ex5 -Force -ErrorAction SilentlyContinue
    throw 'Compile did not report 0 errors, 0 warnings. Session Sniper was NOT activated.'
  }
  Write-Host 'Compile OK: 0 errors, 0 warnings.' -ForegroundColor Green
}

try{
  Write-Host ''
  Write-Host 'SESSION SNIPER STANDALONE 0.11' -ForegroundColor Cyan
  Write-Host 'DEMO/PAPER ONLY. This installer does NOT modify the current Sequence 3.78 system.' -ForegroundColor Yellow
  Write-Host ''

  $target=ChooseTarget (DiscoverTargets)
  $dest=Join-Path $target.MQL5 'Experts\TradeZone\SessionSniper'
  New-Item -ItemType Directory -Force -Path $dest | Out-Null

  $tmp=Join-Path $env:TEMP ('TradeZone_SessionSniper_'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  $downloaded=Join-Path $tmp $SourceName
  Download $SourceUrl $downloaded

  # MetaEditor requires the Market-compatible xxx.yyy version format even for this DEMO EA.
  $raw=Get-Content $downloaded -Raw
  $raw=[regex]::Replace($raw,'#property\s+version\s+"[^"]+"','#property version   "1.11"',1)
  Set-Content -LiteralPath $downloaded -Value $raw -Encoding UTF8

  $src=Join-Path $dest $SourceName
  Copy-Item $downloaded $src -Force

  if(!$SkipCompile){
    $meta=FindMetaEditor $target
    if(!$meta){throw 'MetaEditor was not found. Source was copied, but no EA was activated.'}
    CompileOne $meta $src (Join-Path $tmp 'compile_logs')
  }

  Write-Host ''
  Write-Host 'INSTALL COMPLETE.' -ForegroundColor Green
  Write-Host "Installed to: $src" -ForegroundColor White
  if(!$SkipCompile){
    Write-Host "Compiled EX5: $([IO.Path]::ChangeExtension($src,'.ex5'))" -ForegroundColor White
  }
  Write-Host ''
  Write-Host 'NEXT IN MT5:' -ForegroundColor Cyan
  Write-Host '1. Navigator > Expert Advisors > right-click > Refresh.' -ForegroundColor White
  Write-Host '2. Open a NEW XAUUSD M1 chart. Do not use the existing Trade Zone chart.' -ForegroundColor White
  Write-Host '3. Drag SessionSniperEA_v0_11_7030Runner_Demo onto that chart.' -ForegroundColor White
  Write-Host '4. Confirm Algo Trading is allowed and the account is DEMO.' -ForegroundColor White
  Write-Host '5. Leave the current Institutional SMC Sequence EA 3.78 chart unchanged.' -ForegroundColor White
  Write-Host ''
  Write-Host 'Management: ~70% TP at reference 0.50 midpoint; ~30% structural trailing runner to opposite session side.' -ForegroundColor Green
  PauseExit 0
}catch{
  Write-Host ''
  Write-Host ('INSTALL FAILED: '+$_.Exception.Message) -ForegroundColor Red
  Write-Host 'The existing Trade Zone stable installation was not modified.' -ForegroundColor Yellow
  PauseExit 1
}
