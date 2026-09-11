# v4.3 Carry-Forward Zone Lifecycle

## Rule
A D1/H4/H1 institutional zone map remains active until a newer successful institutional analysis replaces it. `PLAN_VALID_MINUTES` is an advisory refresh target only.

## Replacement
With `REQUIRE_AI_FOR_EXECUTION=true`, only an approved AI-used analysis can replace the active execution plan. AI-unavailable fallback attempts remain auditable but do not make a good zone map disappear. A successful AI NO_TRADE analysis is still a valid replacement.

## Live restrictions
Carry-forward never bypasses live safety. M15 acceptance/mitigation, stale MT5 data, excessive spread and current major-news blackout can all block new M1 entries while the zones remain visible. If a released high-impact USD event is newer than the active plan, post-news revalidation is mandatory before execution resumes.

## MT5 protocol
Protocol remains version 3. While carry-forward is enabled, `valid_until_epoch=0` prevents Sequence EA v2.12 from locally aging out the plan. `refresh_due_epoch`, `refresh_due`, `carry_forward_until_replaced` and `plan_lifecycle` provide diagnostics.
