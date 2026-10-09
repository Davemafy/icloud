param([switch]$SkipCompile)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$InstallerVersion='FRONT_FACING_MANUAL_INSTALLER_1.14'
$Host.UI.RawUI.WindowTitle='Trade Zone - One-Click Demo MT5 Installer 1.14'

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
    throw "SHA256 verification failed for $(Split-Path $Path -Leaf). Expected=$(([string]$Expected).ToLowerInvariant()) Actual=$actual. Nothing active was replaced."
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
  if($raw -notmatch $pattern){throw "Could not find $Name in $(Split-Path $Path -Leaf)"}
  $new=[regex]::Replace($raw,$pattern,$replacement,1)
  if($new-ne$raw){Set-Content $Path -Value $new -Encoding UTF8}
}
function PatchDefine([string]$Path,[string]$Name,[string]$Value){
  $raw=Get-Content $Path -Raw
  $pattern='#define\s+'+[regex]::Escape($Name)+'\s+"[^"]*"'
  $replacement='#define '+$Name+' "'+$Value+'"'
  if($raw -notmatch $pattern){throw "Could not find $Name in $(Split-Path $Path -Leaf)"}
  $new=[regex]::Replace($raw,$pattern,$replacement,1)
  if($new-ne$raw){Set-Content $Path -Value $new -Encoding UTF8}
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
function NormalizeMT5DataPath([string]$PathText){
  if([string]::IsNullOrWhiteSpace($PathText)){return ''}
  $p=$PathText.Trim().Trim('"').Trim("'")
  try{$p=[IO.Path]::GetFullPath($p)}catch{}
  return ($p -replace '[\\/]+$','').ToLowerInvariant()
}
function FindUniqueRunningMT5Target($targets){
  # Select automatically only if exactly one RUNNING MT5 executable matches
  # exactly one discovered MQL5 data-folder origin. Ignore unrelated MT4
  # terminal.exe processes; fail closed for two MT5s, portable or ambiguous paths.
  $running=@()
  try{
    $running=@(Get-CimInstance Win32_Process -Filter "Name = 'terminal64.exe' OR Name = 'terminal.exe'" -ErrorAction Stop)
  }catch{
    Write-Host 'Running MT5 detection unavailable; manual folder selection is required.' -ForegroundColor Yellow
    return $null
  }
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
    Write-Host "Only MT5 data folder: $($targets[0].Data)" -ForegroundColor White
    return $targets[0]
  }

  $liveTarget=FindUniqueRunningMT5Target $targets
  if($null-ne$liveTarget){
    Write-Host "AUTO-DETECTED RUNNING MT5 DATA FOLDER: $($liveTarget.Data)" -ForegroundColor Green
    Write-Host 'The only running MT5 terminal matches exactly one discovered data folder.' -ForegroundColor Green
    return $liveTarget
  }

  # Multiple, missing or ambiguous live terminals require an explicit choice.
  # Use the exact folder shown by the LIVE terminal's File > Open Data Folder.
  while($true){
    Write-Host ''
    Write-Host "DETECTED MT5 DATA FOLDERS ($($targets.Count)):" -ForegroundColor Yellow
    for($i=0;$i-lt$targets.Count;$i++){
      Write-Host ("  [{0}] DATA: {1}" -f ($i+1),[string]$targets[$i].Data) -ForegroundColor White
      if($targets[$i].Install){
        Write-Host ("      INSTALL: {0}" -f [string]$targets[$i].Install) -ForegroundColor Gray
      }
    }
    Write-Host 'In the MT5 terminal you use, click File > Open Data Folder.' -ForegroundColor Cyan
    Write-Host 'Paste that exact folder path below (safest), or enter its matching number.' -ForegroundColor Cyan
    $x=Read-Host 'MT5 data folder path or number'
    $choice=$null
    $n=0
    if([int]::TryParse($x,[ref]$n)){
      if($n-ge1-and$n-le$targets.Count){$choice=$targets[$n-1]}
    }else{
      $wanted=NormalizeMT5DataPath $x
      if($wanted){
        foreach($candidate in $targets){
          if((NormalizeMT5DataPath $candidate.Data)-eq$wanted){
            $choice=$candidate
            break
          }
        }
      }
    }
    if(!$choice){
      Write-Host 'Not a recognized MT5 data folder/number. No files changed. Try again.' -ForegroundColor Red
      continue
    }
    Write-Host "SELECTED MT5 DATA FOLDER: $($choice.Data)" -ForegroundColor Green
    $answer=(Read-Host 'Confirm this is the folder opened by your MT5 terminal? (Y/N)').Trim()
    if($answer -match '^(?i:y|yes)$'){return $choice}
    Write-Host 'Not confirmed. No files changed. Select again.' -ForegroundColor Yellow
  }
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
  New-Item -ItemType Directory -Force -Path $LogDir|Out-Null

  # Never place MetaEditor logs inside the managed Experts\TradeZone folder.
  # A running/previous MetaEditor instance can keep those logs open briefly and
  # the old installer then failed before it even reached compilation. A unique
  # temp log makes compilation independent from stale/locked diagnostic files.
  $log=Join-Path $LogDir ($name+'_'+[guid]::NewGuid().ToString('N')+'_compile.log')

  # Remove only the executable we are about to rebuild. The compile log is new.
  Remove-Item $ex5 -Force -ErrorAction SilentlyContinue
  Write-Host "Compiling: $(Split-Path $Src -Leaf)" -ForegroundColor Cyan

  $p=Start-Process -FilePath $Meta -ArgumentList @("/compile:$Src","/log:$log") -PassThru
  $p.WaitForExit()

  # A running MetaEditor can delegate the command and release the launcher
  # process before compilation/log flushing has actually finished. Poll the
  # unique temp log for a real compile summary instead of racing the file handle.
  $txt=''
  $deadline=(Get-Date).AddSeconds(20)
  do{
    if(Test-Path $log){
      try{$txt=Get-Content $log -Raw -ErrorAction Stop}catch{$txt=''}
    }
    if((Test-Path $ex5) -and $txt -match '\d+ errors,\s*\d+ warnings'){break}
    Start-Sleep -Milliseconds 300
  }while((Get-Date)-lt$deadline)

  if(!(Test-Path $ex5)){
    if($txt){
      Write-Host ''
      Write-Host 'MetaEditor compile log:' -ForegroundColor Yellow
      Write-Host $txt -ForegroundColor DarkYellow
    }
    throw "Compilation failed for $(Split-Path $Src -Leaf)."
  }
  if([string]::IsNullOrWhiteSpace($txt)){
    throw "MetaEditor compile log was unavailable for $(Split-Path $Src -Leaf)."
  }
  if($txt -notmatch '0 errors,\s*0 warnings'){
    Write-Host ''
    Write-Host 'MetaEditor compile log:' -ForegroundColor Yellow
    Write-Host $txt -ForegroundColor DarkYellow
    throw "Compile did not report 0 errors, 0 warnings for $(Split-Path $Src -Leaf)."
  }
  Write-Host "  OK: 0 errors, 0 warnings." -ForegroundColor Green
}

function RemoveObsoleteManagedFiles([string]$Dest,[string[]]$KeepNames){
  if(!(Test-Path $Dest)){return}
  $keep=@{}
  foreach($n in @($KeepNames)){if($n){$keep[$n.ToLowerInvariant()]=$true}}

  # Cleanup is best-effort and happens only AFTER the new package has compiled.
  # A locked old log/EX5 must never make an otherwise valid install fail.
  Get-ChildItem $Dest -File -ErrorAction SilentlyContinue | ForEach-Object{
    $name=$_.Name
    $low=$name.ToLowerInvariant()
    $managed=(
      $name -like 'InstitutionalSMC_DataBridge_*.mq5' -or
      $name -like 'InstitutionalSMC_DataBridge_*.ex5' -or
      $name -like 'InstitutionalSMC_SequenceEA_*.mq5' -or
      $name -like 'InstitutionalSMC_SequenceEA_*.ex5' -or
      $name -like '*_compile.log'
    )
    if($managed -and !$keep.ContainsKey($low)){
      try{
        Remove-Item $_.FullName -Force -ErrorAction Stop
      }catch{
        Write-Host "  Cleanup deferred (file in use): $name" -ForegroundColor DarkYellow
      }
    }
  }
}
# The installer must NEVER make installation success depend on a cloud HTTP read.
# Windows PowerShell HTTP timeouts do not impose a strict
# wall-clock deadline on stalled DNS/proxy/TLS handshakes. This previously
# trapped the already-successful install at "Checking cloud dashboard..."
# for many minutes. The live DataBridge transmits the unique installer receipt
# via MT5 heartbeat and /system/status exposes separate disk and running truth.
# Cloud confirmation is asynchronous; do not poll the network here.
# Derive a separate credential file per Railway HTTPS origin so account
# migrations cannot silently reuse a different service's key.
function TZ_SecretPath([string]$CloudUrl){
  $origin=$CloudUrl.Trim().TrimEnd('/').ToLowerInvariant()
  $bytes=[Text.Encoding]::UTF8.GetBytes($origin)
  $sha=[Security.Cryptography.SHA256]::Create()
  try{$hex=[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()}
  finally{$sha.Dispose()}
  return (Join-Path (Join-Path $env:LOCALAPPDATA 'TradeZoneMT5\secrets') ('cloud_'+$hex.Substring(0,24)+'.dpapi'))
}
function TZ_LoadPrivateCloudKey([string]$CloudUrl){
  $path=TZ_SecretPath $CloudUrl
  if(!(Test-Path -LiteralPath $path)){return ''}
  try{
    $cipher=(Get-Content -LiteralPath $path -Raw -ErrorAction Stop).Trim()
    if(!$cipher){return ''}
    # ConvertFrom-SecureString (without -Key) uses Windows user DPAPI.
    $secure=ConvertTo-SecureString -String $cipher -ErrorAction Stop
    $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try{return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}
    finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr);$secure.Dispose()}
  }catch{
    Write-Host 'Stored VPS key is unreadable for this Windows user; re-enter a private key once.' -ForegroundColor Yellow
    return ''
  }
}
function TZ_SavePrivateCloudKey([string]$CloudUrl,[string]$CloudKey){
  $path=TZ_SecretPath $CloudUrl
  $dir=Split-Path -Parent $path
  New-Item -ItemType Directory -Force -Path $dir|Out-Null
  $secure=ConvertTo-SecureString -String $CloudKey -AsPlainText -Force
  try{$cipher=ConvertFrom-SecureString -SecureString $secure -ErrorAction Stop}
  finally{$secure.Dispose()}
  $tmp=$path+'.tmp'
  try{
    [IO.File]::WriteAllText($tmp,$cipher,(New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $path -Force
  }finally{
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
  }
}
# Reuse existing MT5 credentials during the one-time migration between
# the two explicitly known R&D Railway service URLs. No credential values are
# published in source code or retrieved anonymously from Railway.
function TZ_LoadMigrationCloudKey([string]$CloudUrl,[string]$ConfigPath){
  if(!(Test-Path -LiteralPath $ConfigPath)){return ''}
  try{
    $cfg=Get-Content -LiteralPath $ConfigPath -Raw -ErrorAction Stop|ConvertFrom-Json
    $storedUrl=([string]$cfg.cloud_url).Trim().TrimEnd('/')
    $newUrl=$CloudUrl.Trim().TrimEnd('/')
    $same=($storedUrl -eq $newUrl)
    $approvedMigration=(
      $storedUrl -eq 'https://icloud-production-9111.up.railway.app' -and
      $newUrl -eq 'https://icloud-production-c8d3.up.railway.app'
    )
    if(!$same -and !$approvedMigration){return ''}
    $key=TZ_LoadPrivateCloudKey $storedUrl
    if(!$key){$key=[string]$cfg.cloud_api_key}
    if($key){
      if($approvedMigration){Write-Host 'Automatically carrying forward the existing R&D key from the old Railway URL.' -ForegroundColor Green}
      else{Write-Host 'Reusing the existing MT5 VPS key for this Railway URL.' -ForegroundColor Green}
    }
    return $key
  }catch{
    Write-Host 'Existing VPS key could not be read; local key input may be needed.' -ForegroundColor Yellow
    return ''
  }
}
function SaveManagedConfig($T,[string]$CloudUrl,[string]$CloudKey){
  # Persist credential once, encrypted for the installing Windows user. Keep
  # the app config key-free; older plaintext config is migrated on next install.
  TZ_SavePrivateCloudKey $CloudUrl $CloudKey
  $root=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5'
  New-Item -ItemType Directory -Force -Path $root|Out-Null
  $cfg=Join-Path $root 'config.json'
  $obj=[ordered]@{
    target_data_folder=$T.Data
    mt5_install_path=$T.Install
    cloud_url=$CloudUrl
    cloud_key_storage='WINDOWS_DPAPI_CURRENT_USER'
    mode='MANUAL_ONLY'
    background_updater='DISABLED'
  }
  $tmp=$cfg+'.tmp'
  try{
    [IO.File]::WriteAllText($tmp,($obj|ConvertTo-Json -Depth 8),(New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $cfg -Force
  }finally{
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
  }
}

Write-Host '================================================================' -ForegroundColor Cyan
Write-Host (" Trade Zone - ONE-CLICK DEMO MT5 INSTALLER 1.14") -ForegroundColor Cyan
Write-Host ' Current EA names + private VPS key + GitHub cloud URL' -ForegroundColor Cyan
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

  $cloudUrl=([string]$m.demo_defaults.cloud_base_url).Trim().TrimEnd('/')
  if($cloudUrl -notmatch '^https://[^/]+$'){
    throw 'Stable manifest has no valid HTTPS cloud origin.'
  }

  # Secrets must never be distributed by public GitHub manifest, even for demo.
  if(-not [string]::IsNullOrWhiteSpace([string]$m.demo_defaults.cloud_api_key)){
    throw 'Unsafe public manifest contains a cloud API key. Remove it before installing.'
  }
  $cloudKey=TZ_LoadPrivateCloudKey $cloudUrl
  if($cloudKey){Write-Host 'Using automatically saved VPS cloud key (Windows DPAPI).' -ForegroundColor Green}
  $localCfg=Join-Path $env:LOCALAPPDATA 'TradeZoneMT5\config.json'
  # Existing config is valid for its own URL; in this specific R&D account
  # migration it can also supply the same key from the prior Railway URL.
  # On success the new URL gets a DPAPI copy and config.json becomes key-free.
  if(!$cloudKey){
    $cloudKey=TZ_LoadMigrationCloudKey $cloudUrl $localCfg
  }
  # Explicit VPS environment key overrides an older saved key, enabling
  # intentional Railway key rotation without editing local config files.
  # The successful value is saved for future unattended version updates.
  $overrideKey=[string]$env:TRADEZONE_CLOUD_API_KEY
  if(!$overrideKey){$overrideKey=[string]$env:CLOUD_EA_API_KEY}
  if($overrideKey){
    $cloudKey=$overrideKey
    Write-Host 'Using the VPS-provisioned private key; no interactive key entry.' -ForegroundColor Green
  }
  # Research/demo compatibility: do not discard the existing short key merely
  # because it is short. It is the user's current R&D configuration.
  if($cloudKey -and $cloudKey -notmatch '^[A-Za-z0-9_-]+$'){
    Write-Host 'Stored API key contains unsupported characters.' -ForegroundColor Yellow
    $cloudKey=''
  }
  if(!$cloudKey){
    Write-Host ''
    Write-Host 'RAILWAY SETUP: Service > Variables > CLOUD_EA_API_KEY' -ForegroundColor Yellow
    Write-Host 'Enter the same private key here. It is NOT downloaded from GitHub or printed.' -ForegroundColor Cyan
    $secureKey=Read-Host 'CLOUD_EA_API_KEY (hidden input)' -AsSecureString
    $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try{$cloudKey=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}
    finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr);$secureKey.Dispose()}
  }
  if([string]::IsNullOrWhiteSpace($cloudKey) -or $cloudKey -notmatch '^[A-Za-z0-9_-]+$'){
    throw 'CLOUD_EA_API_KEY must match Railway and contain URL-safe letters/numbers/_/-. No files installed.'
  }
  if($cloudKey.Length -lt 24){
    Write-Warning 'Short R&D/demo key reused for compatibility; this publicly exposed legacy key is not secure. Rotate before non-R&D use.'
  }

  Write-Host "Release $($m.release) | Bridge v$($m.data_bridge_version) | Sequence v$($m.sequence_ea_version)" -ForegroundColor Green
  Write-Host "Demo cloud URL: $cloudUrl" -ForegroundColor DarkCyan
  Write-Host 'Demo API key: locally configured (value hidden).' -ForegroundColor DarkCyan

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

  # Back up the complete TradeZone tree. Do NOT destructively clean the live
  # directory before the replacement package has compiled successfully.
  if(Test-Path $dest){
    Copy-Item $dest (Join-Path $expertsBackup 'TradeZone') -Recurse -Force
    Write-Host 'Existing TradeZone tree backed up before update.' -ForegroundColor DarkCyan
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
    $compileLogDir=Join-Path $tmp 'compile_logs'
    foreach($src in $srcs){CompileOne $meta $src $compileLogDir}
  }

  # New sources/executables are now in place. Prune only obsolete managed
  # front-facing files, and never fail the install if an old diagnostic/ex5 is
  # temporarily locked by MT5/MetaEditor.
  $keepNames=@()
  foreach($src in $srcs){
    $keepNames+=(Split-Path $src -Leaf)
    $keepNames+=([IO.Path]::GetFileName([IO.Path]::ChangeExtension($src,'.ex5')))
  }
  RemoveObsoleteManagedFiles $dest $keepNames

  # Publish disk-install truth only after every download is verified and every
  # front-facing EA has compiled successfully. DataBridge reads this exact file.
  $statusDir=Join-Path $t.MQL5 'Files\TradeZone'
  New-Item -ItemType Directory -Force -Path $statusDir|Out-Null
  $statusFile=Join-Path $statusDir 'updater_status.txt'
  $installReceipt='MANUAL_INSTALL_COMPILED_'+[guid]::NewGuid().ToString('N')
  # PowerShell's '+' and comma expression precedence can collapse a key/value
  # array into ONE space-joined string. Emit each line explicitly instead.
  $statusLines=New-Object 'System.Collections.Generic.List[string]'
  [void]$statusLines.Add(('updater_version='+$InstallerVersion))
  [void]$statusLines.Add(('stable_release='+[string]$m.release))
  [void]$statusLines.Add(('desired_bridge_version='+[string]$m.data_bridge_version))
  [void]$statusLines.Add(('desired_sequence_version='+[string]$m.sequence_ea_version))
  [void]$statusLines.Add(('installed_bridge_version='+[string]$m.data_bridge_version))
  [void]$statusLines.Add(('installed_sequence_version='+[string]$m.sequence_ea_version))
  [void]$statusLines.Add('pending_reload=1')
  [void]$statusLines.Add('result=INSTALLED_REATTACH_REQUIRED')
  [void]$statusLines.Add('update_result=INSTALLED_REATTACH_REQUIRED')
  [void]$statusLines.Add(('last_action='+$installReceipt))
  if($statusLines.Count-ne10){throw 'Installer status serialization produced the wrong field count.'}
  $statusTmp=$statusFile+'.tmp'
  [IO.File]::WriteAllLines($statusTmp,[string[]]$statusLines.ToArray(),(New-Object System.Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $statusTmp -Destination $statusFile -Force
  # Check the exact status file in the selected MT5 data folder.
  $readBackLines=@(Get-Content -LiteralPath $statusFile -ErrorAction Stop)
  if($readBackLines.Count-ne10){throw "Installed-status must have 10 separate lines; found $($readBackLines.Count)."}
  foreach($expected in $statusLines){
    if($readBackLines -notcontains $expected){
      throw "Installed-status readback mismatch for $expected in $statusFile"
    }
  }
  Write-Host "Disk version truth VERIFIED at: $statusFile" -ForegroundColor Green

  SaveManagedConfig $t $cloudUrl $cloudKey
  # Success is local, deterministic, and independent of cloud availability.
  # The running DataBridge picks up updater_status.txt on its next heartbeat.
  # NEVER declare Sequence 3.78 running until its own MT5 heartbeat proves it.
  Write-Host ''
  Write-Host 'SUCCESS: MT5 DISK INSTALL VERIFIED. INSTALLER FINISHED.' -ForegroundColor Green
  Write-Host 'CLOUD ACKNOWLEDGEMENT: ASYNCHRONOUS; installer does not wait on HTTP.' -ForegroundColor Yellow
  Write-Host 'DataBridge forwards the unique install receipt from this MT5 folder on its next heartbeat.' -ForegroundColor Cyan
  Write-Host 'The dashboard must show installed vs running independently; this installer does not claim runtime activation.' -ForegroundColor Cyan
  Write-Host "  Installer $InstallerVersion" -ForegroundColor Green
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
