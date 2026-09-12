param([switch]$SkipCompile)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle='Trade Zone - GitHub MT5 Installer'

$Repo='Davemafy/icloud'
$Branch='main'
$ManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/stable/manifest.json"

function PauseExit([int]$Code=0){Write-Host '';Read-Host 'Press ENTER to close';exit $Code}
function Download([string]$Url,[string]$Out){Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 45;if(!(Test-Path $Out)){throw "Download failed: $Url"}}
function FindMetaEditor($T){
  $c=@();if($T.Install){$b=$T.Install;if(Test-Path $b -PathType Leaf){$b=Split-Path -Parent $b};$c+=Join-Path $b 'metaeditor64.exe';$c+=Join-Path $b 'MetaEditor64.exe';$c+=Join-Path $b 'metaeditor.exe'}
  foreach($r in @($env:ProgramFiles,${env:ProgramFiles(x86)})){if($r){$c+=Join-Path $r 'MetaTrader 5\metaeditor64.exe';$c+=Join-Path $r 'MetaTrader 5\MetaEditor64.exe'}}
  foreach($p in $c){if($p-and(Test-Path $p)){return $p}};return $null
}

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' Trade Zone - ONE GitHub MT5 Installer' -ForegroundColor Cyan
Write-Host ' GitHub -> SHA256 verify -> archive old -> install -> compile' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan

$tmp=Join-Path $env:TEMP ('TradeZone_'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -Force -Path $tmp|Out-Null
try{
  $mf=Join-Path $tmp 'manifest.json';Write-Host 'Downloading stable manifest...' -ForegroundColor Cyan;Download $ManifestUrl $mf
  $m=Get-Content $mf -Raw|ConvertFrom-Json
  if($m.schema-ne1-or!$m.files){throw 'Unsupported stable manifest.'};if($m.repository-ne$Repo){throw 'Manifest repository mismatch.'}
  Write-Host "Release $($m.release) | Bridge v$($m.data_bridge_version) | Sequence v$($m.sequence_ea_version)" -ForegroundColor Green

  $dl=@();foreach($f in $m.files){
    $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)";$o=Join-Path $tmp $f.name
    Write-Host "Downloading $($f.name)..." -ForegroundColor Cyan;Download $u $o
    $actual=(Get-FileHash -Algorithm SHA256 $o).Hash.ToLowerInvariant();$expected=([string]$f.sha256).ToLowerInvariant()
    if($actual-ne$expected){throw "SHA256 verification failed for $($f.name). Nothing will be installed."}
    Write-Host '  SHA256 verified.' -ForegroundColor Green;$dl+=[PSCustomObject]@{Name=$f.name;Path=$o}
  }

  $root=Join-Path $env:APPDATA 'MetaQuotes\Terminal';if(!(Test-Path $root)){throw 'MT5 terminal data root not found.'}
  $inst=@();Get-ChildItem $root -Directory|ForEach-Object{$mq=Join-Path $_.FullName 'MQL5';if(Test-Path $mq){$or=Join-Path $_.FullName 'origin.txt';$ip=$null;if(Test-Path $or){try{$ip=(Get-Content $or -Raw).Trim()}catch{}};$inst+=[PSCustomObject]@{Data=$_.FullName;MQL5=$mq;Install=$ip}}}
  if($inst.Count-eq0){throw 'No MT5 data folder found.'}
  if($inst.Count-eq1){$t=$inst[0]}else{Write-Host 'Choose the MT5 instance:' -ForegroundColor Yellow;for($i=0;$i-lt$inst.Count;$i++){$lab=$inst[$i].Install;if([string]::IsNullOrWhiteSpace($lab)){$lab=$inst[$i].Data};Write-Host " [$($i+1)] $lab"};do{$x=Read-Host 'Number';$n=0;$ok=[int]::TryParse($x,[ref]$n)}until($ok-and$n-ge1-and$n-le$inst.Count);$t=$inst[$n-1]}

  $dest=Join-Path $t.MQL5 'Experts\TradeZone';New-Item -ItemType Directory -Force -Path $dest|Out-Null;Write-Host "MT5 data folder: $($t.Data)" -ForegroundColor Green
  $old=@(Get-ChildItem $dest -File -ErrorAction SilentlyContinue|Where-Object{$_.Name-like'InstitutionalSMC_DataBridge_v*.*'-or$_.Name-like'InstitutionalSMC_SequenceEA_v*.*'})
  if($old.Count-gt0){$arc=Join-Path $dest ('_archive\'+(Get-Date -Format 'yyyyMMdd_HHmmss'));New-Item -ItemType Directory -Force -Path $arc|Out-Null;foreach($f in $old){Move-Item $f.FullName (Join-Path $arc $f.Name)-Force};Write-Host "Archived previous versions to: $arc" -ForegroundColor DarkGray}

  $srcs=@();foreach($f in $dl){$d=Join-Path $dest $f.Name;Copy-Item $f.Path $d -Force;$srcs+=$d};Write-Host 'Verified source files installed:' -ForegroundColor Green;foreach($s in $srcs){Write-Host "  $s"}
  if($SkipCompile){PauseExit 0}

  $me=FindMetaEditor $t;if(!$me){Write-Host 'MetaEditor not found. Compile the installed .mq5 files manually with F7.' -ForegroundColor Yellow;Start-Process explorer.exe -ArgumentList "`"$dest`"";PauseExit 2}
  Write-Host "MetaEditor: $me" -ForegroundColor Cyan;$all=$true
  foreach($src in $srcs){$name=[IO.Path]::GetFileNameWithoutExtension($src);$ex5=[IO.Path]::ChangeExtension($src,'.ex5');$log=Join-Path $dest ($name+'_compile.log');Remove-Item $ex5,$log -Force -ErrorAction SilentlyContinue;Write-Host "Compiling: $(Split-Path $src -Leaf)" -ForegroundColor Cyan;Start-Process -FilePath $me -ArgumentList @("/compile:$src","/log:$log") -Wait|Out-Null;Start-Sleep -Milliseconds 700;if(Test-Path $log){Get-Content $log -Tail 30|ForEach-Object{Write-Host $_}};if(Test-Path $ex5){Write-Host "OK: $(Split-Path $ex5 -Leaf)" -ForegroundColor Green}else{Write-Host "FAILED: $(Split-Path $src -Leaf)" -ForegroundColor Red;$all=$false}}

  Write-Host ''
  if($all){Write-Host 'SUCCESS: BOTH EAs DOWNLOADED, VERIFIED, INSTALLED AND COMPILED.' -ForegroundColor Green;Write-Host 'MT5: Navigator > Expert Advisors > right-click Refresh > TradeZone.' -ForegroundColor Cyan;Write-Host 'Attach DataBridge ONCE to XAUUSD; attach Sequence EA to XAUUSD M1.' -ForegroundColor Cyan;Write-Host 'Keep DEMO/PAPER_ONLY while validating.' -ForegroundColor Yellow;PauseExit 0}
  Write-Host "Compilation failed. Logs are in $dest" -ForegroundColor Yellow;Start-Process explorer.exe -ArgumentList "`"$dest`"";PauseExit 3
}catch{Write-Host '';Write-Host "INSTALLER FAILED: $($_.Exception.Message)" -ForegroundColor Red;Write-Host 'Unverified downloads are not installed.' -ForegroundColor Yellow;PauseExit 1}
finally{Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue}
