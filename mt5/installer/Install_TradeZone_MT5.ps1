param([switch]$SkipCompile)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle='Trade Zone - One-Click Demo MT5 Installer'

$Repo='Davemafy/icloud'
$Branch='main'
$ManifestUrl="https://raw.githubusercontent.com/$Repo/$Branch/mt5/stable/manifest.json"

function PauseExit([int]$Code=0){Write-Host '';Read-Host 'Press ENTER to close';exit $Code}
function Download([string]$Url,[string]$Out){
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 60
  if(!(Test-Path $Out)){throw "Download failed: $Url"}
  Unblock-File -LiteralPath $Out -ErrorAction SilentlyContinue
}
function Verify([string]$Path,[string]$Expected){
  if([string]::IsNullOrWhiteSpace($Expected)){throw "Missing SHA256 for $(Split-Path $Path -Leaf)"}
  $actual=(Get-FileHash -Algorithm SHA256 $Path).Hash.ToLowerInvariant()
  if($actual-ne([string]$Expected).ToLowerInvariant()){
    throw "SHA256 verification failed for $(Split-Path $Path -Leaf). Nothing active was replaced."
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
  foreach($p in $c){if($p-and(Test-Path $p)){return $p}}
  return $null
}
function PatchInput([string]$Path,[string]$Name,[string]$Value){
  $raw=Get-Content $Path -Raw
  $pattern='input\s+string\s+'+[regex]::Escape($Name)+'="[^"]*";'
  $replacement='input string '+$Name+'="'+$Value+'";'
  $new=[regex]::Replace($raw,$pattern,$replacement,1)
  if($new-eq$raw){throw "Could not set $Name in $(Split-Path $Path -Leaf)"}
  Set-Content $Path -Value $new -Encoding UTF8
}
function PatchDefine([string]$Path,[string]$Name,[string]$Value){
  $raw=Get-Content $Path -Raw
  $pattern='#define\s+'+[regex]::Escape($Name)+'\s+"[^"]*"'
  $replacement='#define '+$Name+' "'+$Value+'"'
  $new=[regex]::Replace($raw,$pattern,$replacement,1)
  if($new-eq$raw){throw "Could not set $Name in $(Split-Path $Path -Leaf)"}
  Set-Content $Path -Value $new -Encoding UTF8
}
function DiscoverTargets(){
  $root=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
  if(!(Test-Path $root)){throw 'MT5 terminal data root not found.'}
  $inst=@()
  Get-ChildItem $root -Directory|ForEach-Object{
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
function ChooseTarget($inst){
  if($inst.Count-eq0){throw 'No MT5 data folder found.'}
  if($inst.Count-eq1){return $inst[0]}

  # Prefer the previously managed TradeZone target if available.
  $cfg=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5\config.json'
  if(Test-Path $cfg){
    try{
      $c=Get-Content $cfg -Raw|ConvertFrom-Json
      $saved=[string]$c.target_data_folder
      foreach($x in $inst){if($x.Data-eq$saved){return $x}}
    }catch{}
  }

  Write-Host 'Choose the MT5 instance:' -ForegroundColor Yellow
  for($i=0;$i-lt$inst.Count;$i++){
    $lab=$inst[$i].Install
    if([string]::IsNullOrWhiteSpace($lab)){$lab=$inst[$i].Data}
    Write-Host " [$($i+1)] $lab"
  }
  do{
    $x=Read-Host 'Number';$n=0;$ok=[int]::TryParse($x,[ref]$n)
  }until($ok-and$n-ge1-and$n-le$inst.Count)
  return $inst[$n-1]
}
function BackupFile([string]$Path,[string]$BackupRoot,[string]$Name){
  if(Test-Path $Path){
    New-Item -ItemType Directory -Force -Path $BackupRoot|Out-Null
    Copy-Item $Path (Join-Path $BackupRoot $Name) -Force
  }
}
function CompileOne([string]$Meta,[string]$Src,[string]$LogDir){
  $name=[IO.Path]::GetFileNameWithoutExtension($Src)
  $ex5=[IO.Path]::ChangeExtension($Src,'.ex5')
  $log=Join-Path $LogDir ($name+'_compile.log')
  Remove-Item $ex5,$log -Force -ErrorAction SilentlyContinue
  Write-Host "Compiling: $(Split-Path $Src -Leaf)" -ForegroundColor Cyan
  Start-Process -FilePath $Meta -ArgumentList @("/compile:$Src","/log:$log") -Wait|Out-Null
  Start-Sleep -Milliseconds 900
  if(!(Test-Path $ex5)){throw "Compilation failed for $(Split-Path $Src -Leaf)."}
  $txt=if(Test-Path $log){Get-Content $log -Raw}else{''}
  if($txt -and $txt -notmatch '0 errors,\s*0 warnings'){
    throw "Compile did not report 0 errors, 0 warnings for $(Split-Path $Src -Leaf)."
  }
  Write-Host "  OK: 0 errors, 0 warnings." -ForegroundColor Green
}
function SaveManagedConfig($T,[string]$CloudUrl,[string]$CloudKey){
  $root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
  New-Item -ItemType Directory -Force -Path $root|Out-Null
  $cfg=Join-Path $root 'config.json'
  $obj=[ordered]@{
    target_data_folder=$T.Data
    mt5_install_path=$T.Install
    cloud_url=$CloudUrl
    cloud_api_key=$CloudKey
    mode='MANUAL_ONLY'
    background_updater='DISABLED'
  }
  $obj|ConvertTo-Json -Depth 8|Set-Content $cfg -Encoding UTF8
}

Write-Host '================================================================' -ForegroundColor Cyan
Write-Host ' Trade Zone - ONE-CLICK DEMO MT5 INSTALLER' -ForegroundColor Cyan
Write-Host ' Current EA names + built-in demo cloud URL/key defaults' -ForegroundColor Cyan
Write-Host ' No background updater / no scheduled task' -ForegroundColor Yellow
Write-Host '================================================================' -ForegroundColor Cyan

$tmp=Join-Path $env:TEMP ('TradeZone_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp|Out-Null

try{
  $mf=Join-Path $tmp 'manifest.json'
  Write-Host 'Downloading stable manifest...' -ForegroundColor Cyan
  Download $ManifestUrl $mf
  $m=Get-Content $mf -Raw|ConvertFrom-Json
  if($m.schema-ne1-or!$m.files){throw 'Unsupported stable manifest.'}
  if($m.repository-ne$Repo){throw 'Manifest repository mismatch.'}
  if(!$m.demo_defaults){throw 'Stable manifest has no demo_defaults block.'}

  $cloudUrl=[string]$m.demo_defaults.cloud_base_url
  $cloudKey=[string]$m.demo_defaults.cloud_api_key
  if([string]::IsNullOrWhiteSpace($cloudUrl)-or[string]::IsNullOrWhiteSpace($cloudKey)){
    throw 'Demo cloud defaults are incomplete.'
  }

  Write-Host "Release $($m.release) | Bridge v$($m.data_bridge_version) | Sequence v$($m.sequence_ea_version)" -ForegroundColor Green
  Write-Host "Demo cloud URL: $cloudUrl" -ForegroundColor DarkCyan
  Write-Host "Demo API key : $cloudKey" -ForegroundColor DarkCyan

  # Download and verify ALL source/support files before touching the active MT5 tree.
  $fileDownloads=@()
  foreach($f in @($m.files)){
    $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
    $o=Join-Path $tmp ('file_'+$f.name)
    Write-Host "Downloading $($f.name)..." -ForegroundColor Cyan
    Download $u $o
    Verify $o ([string]$f.sha256)
    Write-Host '  SHA256 verified.' -ForegroundColor Green
    $fileDownloads+=[PSCustomObject]@{Def=$f;Path=$o}
  }

  $supportDownloads=@()
  foreach($f in @($m.support_files)){
    $u="https://raw.githubusercontent.com/$($m.repository)/$($m.ref)/$($f.path)"
    $o=Join-Path $tmp ('support_'+$f.name)
    Write-Host "Downloading support $($f.name)..." -ForegroundColor Cyan
    Download $u $o
    Verify $o ([string]$f.sha256)
    Write-Host '  SHA256 verified.' -ForegroundColor Green
    $supportDownloads+=[PSCustomObject]@{Def=$f;Path=$o}
  }

  # Inject demo defaults into the verified temporary support sources.
  foreach($x in $supportDownloads){
    if([string]$x.Def.role-eq'data_bridge_core'){
      PatchInput $x.Path 'CloudBaseUrl' $cloudUrl
      PatchInput $x.Path 'CloudApiKey' $cloudKey
      PatchInput $x.Path 'SequenceEaVersion' ([string]$m.sequence_ea_version)
    }
    if([string]$x.Def.role-eq'sequence_core'){
      PatchInput $x.Path 'CloudBaseUrl' $cloudUrl
      PatchInput $x.Path 'CloudApiKey' $cloudKey
    }
  }
  foreach($x in $fileDownloads){
    if([string]$x.Def.role-eq'data_bridge'){
      # Keep bridge heartbeat expectation aligned with the current Sequence runtime.
      try{PatchDefine $x.Path 'TZ_SEQUENCE_EXPECTED' ([string]$m.sequence_ea_version)}catch{
        Write-Host 'Bridge wrapper has no TZ_SEQUENCE_EXPECTED patch point; continuing.' -ForegroundColor DarkYellow
      }
    }
  }

  $inst=DiscoverTargets
  $t=ChooseTarget $inst
  Write-Host "MT5 data folder: $($t.Data)" -ForegroundColor Green

  $meta=FindMetaEditor $t
  if(!$SkipCompile-and!$meta){throw 'MetaEditor not found.'}

  $dest=Join-Path $t.MQL5 'Experts\TradeZone'
  $backupRoot=Join-Path $env:LOCALAPPDATA ('TradeZoneMT5\backups\installer_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
  $includeBackup=Join-Path $backupRoot 'include'
  $expertsBackup=Join-Path $backupRoot 'experts'
  New-Item -ItemType Directory -Force -Path $includeBackup,$expertsBackup|Out-Null

  # Back up the complete TradeZone tree, then refresh only root-level managed EA files.
  # Child folders (for example Observer) are intentionally preserved.
  if(Test-Path $dest){
    Copy-Item $dest (Join-Path $expertsBackup 'TradeZone') -Recurse -Force
    Get-ChildItem $dest -File -ErrorAction SilentlyContinue | ForEach-Object{
      Remove-Item $_.FullName -Force
    }
    Write-Host 'Preserved existing TradeZone subfolders (including Observer).' -ForegroundColor DarkCyan
  }else{
    New-Item -ItemType Directory -Force -Path $dest|Out-Null
  }

  # Install patched support sources.
  foreach($x in $supportDownloads){
    $targetRoot=Join-Path $t.MQL5 ([string]$x.Def.target)
    New-Item -ItemType Directory -Force -Path $targetRoot|Out-Null
    $target=Join-Path $targetRoot ([string]$x.Def.target_name)
    BackupFile $target $includeBackup ([string]$x.Def.target_name)
    Copy-Item $x.Path $target -Force
  }

  # Install only the current front-facing EA sources.
  $srcs=@()
  foreach($x in $fileDownloads){
    $name=[string]$x.Def.target_name
    if([string]::IsNullOrWhiteSpace($name)){$name=[string]$x.Def.name}
    $d=Join-Path $dest $name
    Copy-Item $x.Path $d -Force
    $srcs+=$d
  }

  if(!$SkipCompile){
    foreach($src in $srcs){CompileOne $meta $src $dest}
  }

  SaveManagedConfig $t $cloudUrl $cloudKey

  Write-Host ''
  Write-Host 'SUCCESS: CURRENT TRADE ZONE EAs INSTALLED.' -ForegroundColor Green
  Write-Host "  DataBridge v$($m.data_bridge_version)" -ForegroundColor Green
  Write-Host "  Sequence EA v$($m.sequence_ea_version)" -ForegroundColor Green
  Write-Host "  Cloud URL/key are already the EA defaults." -ForegroundColor Green
  Write-Host "  Old TradeZone Navigator tree backed up to: $expertsBackup" -ForegroundColor DarkGray
  Write-Host '  Existing TradeZone subfolders were preserved.' -ForegroundColor DarkGray
  Write-Host ''
  Write-Host 'MT5: Navigator > Expert Advisors > right-click Refresh > TradeZone.' -ForegroundColor Cyan
  Write-Host 'Attach DataBridge once to XAUUSD; attach Sequence EA to XAUUSD M1.' -ForegroundColor Cyan
  Write-Host 'Add the Railway URL once under Tools > Options > Expert Advisors > Allow WebRequest.' -ForegroundColor Yellow
  Write-Host 'Keep DEMO/PAPER_ONLY while validating.' -ForegroundColor Yellow
  PauseExit 0
}
catch{
  Write-Host ''
  Write-Host "INSTALLER FAILED: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host 'Downloaded files failed closed. Review the message before retrying.' -ForegroundColor Yellow
  PauseExit 1
}
finally{
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
