# Installer 1.7: unblock completed installations from stalled cloud checks

**Scope:** DEMO/PAPER_ONLY. This is a front-facing installer change only. MT5
Sequence EA 3.78, DataBridge 1.59, Cloud 6.5.143, and the stable release
manifest 6.4.20 are not changed.

## Incident
Installer 1.6 compiled both EAs with zero errors, SHA256-verified every
download, wrote and read back the ten-field version-truth status file, then
appeared frozen for multiple minutes at `Checking cloud dashboard
acknowledgement...`. The synchronous Windows PowerShell HTTP request
(`Invoke-RestMethod -TimeoutSec 6`) was inside a 45-second retry loop; the
timeout on the request was not an enforceable end-to-end wall-clock bound
(DNS/proxy/TLS/network stalls can outlive it). This left an already verified
installation looking like a failure.

## Fix
Installer 1.7 removes synchronous cloud polling entirely from the installer
success path. The installer now exits the installation path immediately after
compile, version-truth readback, and managed-config write. It prints
`SUCCESS: MT5 DISK INSTALL VERIFIED. INSTALLER FINISHED.` and explicitly
marks cloud acknowledgement **ASYNCHRONOUS**, never as already proven.

The ten key/value fields, unique `last_action=MANUAL_INSTALL_COMPILED_<GUID>`
receipt, and installation folder are unchanged:
`<selected MT5 data folder>/MQL5/Files/TradeZone/updater_status.txt`.

The running DataBridge 1.59 reads this file using
`FileOpen("TradeZone\\updater_status.txt",FILE_READ|FILE_TXT|FILE_ANSI)`
and sends it to `/mt5/heartbeat`. The Cloud dashboard's
`/system/status` reads that heartbeat and distinguishes GitHub desired,
installer-installed on disk, and actually running in MT5. The installer
does **not** claim that Sequence 3.78 is running until an MT5 Sequence 3.78
heartbeat proves activation.

## Operational response for users stuck in installer 1.6
If the final green line said `Disk version truth VERIFIED at: ...`, then
both components had already compiled and the status file had been written and
read back. Closing that stuck installer does not uninstall or undo the disk
installation. No further installation is required solely to escape the
acknowledgement step.

When **Sequence positions == 0**, refresh Navigator and reattach the approved
Sequence 3.78 to XAUUSD M1 to change the *running* version. Never forcibly
reload a Sequence EA managing open positions.

If the dashboard remains at installed `—` or older values, diagnose a
separate DataBridge path/heartbeat issue: confirm the attached DataBridge runs
against the same folder selected by installer, its `/mt5/heartbeat` is fresh,
and `/system/status` shows the new unique `last_action` receipt.
Cloud acknowledgement remains an independent verification, not an installer
success prerequisite.

## Invariants
- Never install unverified SHA256 payloads.
- Never report success until compilation and disk readback succeed.
- Never wait for external/cloud network in the local install completion path.
- Never infer runtime version from source filename or the disk status alone.
- Preserve existing trading positions and all Model 1/2/3/canonical liquidity,
  campaign/stop/risk logic unchanged.

## Verification
Static regression tests enforce no blocking `Invoke-RestMethod` in the
installer, proper disk receipt and version-truth readback, and the already
existing Cloud/DataBridge heartbeat integration contract. Windows installer
execution and actual dashboard runtime activation still require validation
on the user's VPS/MT5 environment.
