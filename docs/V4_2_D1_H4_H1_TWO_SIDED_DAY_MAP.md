# V4.2 — D1/H4/H1 Two-Sided Institutional Day Map

## Purpose
Restore the original manual top-down zone process: XAU D1, H4 and H1 jointly create the institutional supply/demand map.

## Zone authority
1. D1 identifies macro parent supply/demand, external range, major liquidity and broad reversal/continuation locations.
2. H4 refines the Daily parent zone and active institutional leg.
3. H1 provides the preferred intraday executable boundary.
4. M15 qualifies the already-derived zone once; it does not originate a standalone zone and is not an entry delay.
5. M1 is the sole execution authority.

Preferred stacks: D1>H4>H1, D1>H4, H4>H1, D1>H1, then H1-only if non-conflicting. Broad D1-only boxes are context until refined.

## Two-sided day map
The deterministic engine searches both sides of XAU. When observed evidence exists, it keeps at most one best BUY zone and one best SELL zone. On a directional D1/H4/H1 day, the same-direction zone is CONTINUATION and the opposite-side zone is REVERSAL. When the top-down stack is neutral they are TRANSITION_BUY and TRANSITION_SELL. A missing side is never invented.

## DXY
DXY D1/H4/H1 is analysis-only. Each XAU BUY/SELL candidate is graded against the DXY direction that would support that specific candidate, so reversal zones are not accidentally scored using the main-trend DXY implication.

## Live invalidation
M15 remains the zone-health guard after publication using the v4.1 body/ATR acceptance rules. It can block a zone but cannot create or re-confirm an entry.
