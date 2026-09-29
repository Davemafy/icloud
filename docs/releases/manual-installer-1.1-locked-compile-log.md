# Manual installer 1.1 — locked compile-log resilience

Status: DEMO / PAPER ONLY

This installer-only fix addresses a Windows/MetaEditor failure where a previous
or delegated MetaEditor process could keep an old
`*_compile.log` file open inside `MQL5\Experts\TradeZone`.

The old installer performed destructive root-level cleanup before compiling the
replacement package. With `$ErrorActionPreference='Stop'`, one locked compile
log could abort the install before compilation began.

Installer 1.1 changes the flow:

1. Back up the existing TradeZone tree.
2. Leave the active root tree intact while staging the new sources.
3. Compile using a unique log under the installer's temporary directory, never
   inside `Experts\TradeZone`.
4. Poll up to 20 seconds for the actual MetaEditor compile summary to avoid the
   delegated-process/log-flush race.
5. Require an explicit `0 errors, 0 warnings` compile result.
6. Only after successful compilation, prune obsolete managed root files.
7. If an old EX5 or compile log is still locked by MT5/MetaEditor, cleanup is
   deferred with a warning instead of failing the valid install.

This does not change Cloud 6.5.109, Stable 6.3.40, DataBridge 1.57 or Sequence
3.47. The same one-click BAT downloads the current installer script from GitHub
main, so no new launcher is required after this fix is merged.
