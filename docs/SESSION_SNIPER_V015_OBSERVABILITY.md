# Session Sniper v0.15 — read-only session information panel

**Release stage:** DEMO / PAPER candidate. This commit is NOT installed or compiled on the user's VPS.
It is not part of the MT5 stable 6.4.20 package; Sequence EA 3.78 and DataBridge 1.59 are untouched.

## What changes
A non-trading chart-object overlay on the standalone Session Sniper chart, refreshed once per second by the existing timer, shows both London and New York:

- Session-local day identity (YYYYMMDD).
- Lifecycle status: WAITING, BUILDING REFERENCE, DATA INCOMPLETE, ARMED, SWEEP FOUND, RECLAIMED, DISPLACED, DONE.
- Today's completed 08:00–09:00 high, low and midpoint; placeholders before closure.
- Nearest qualified H1 external BSL/SSL with SWING/FVG classification.
- Current M1 execution stage and last reason.

The overlay uses dedicated `SS_INFO_*` objects. It does not call `/mt5/plan`, change Session Sniper strategy decisions, modify its 70/30 management, or touch any stable Sequence files. Session-local and broker-offset calculations are inherited unchanged from v0.14. The first panel update should not display previous-day session levels.

## Install / validation gate
1. Run Python source-contract tests for Session Sniper on the candidate branch.
2. On a DEMO hedging MT5 VPS, compile v0.15 with **0 errors and 0 warnings**, collecting the actual MetaEditor log. Compilation has not been performed in GitHub.
3. Attach v0.15 to a **separate XAUUSD M1** chart, after verifying no open Session Sniper positions; retain the v0.14 installation as rollback.
4. Check status at London/NY 07:59, 08:30 and 09:01 local, on UK/US DST boundary dates and on a weekday.
5. Verify the chart-level status/levels match the EA state-file and broker M1 candles; ensure both EA families maintain distinct orders and magic.
6. Confirm that missing historical M1 data produces DATA INCOMPLETE, not yesterday's valid-looking levels.
7. Do not merge into stable or assert MT5 runtime success before these validations.

Installer is deliberately pinned to the new immutable source commit `0ecd3db7abad6b79775d2faf7f87b7586c3dbe94` on the candidate branch.
