# Entry Engine Clinical Audit — Sequence 3.60

## Scope

This audit covers the live/paper primary XAU M1 entry engine only. HTF zone generation,
M15 accepted invalidation, thesis ownership, target lifecycle, risk sizing, DataBridge,
position management and accepted-zone flip remain separate contracts.

## Root architectural problem found

The primary engine had accumulated several independent patches from 3.49 through 3.53.
Execution and diagnostics used separate detectors. That allowed the dashboard to advance
through one interpretation while the order builder applied another. The engine also
encoded several constraints that were not part of the user's stated sniper model.

The correction is a consolidated scanner: the same function now produces the execution
candidate, the stage shown on the dashboard and the exact trace values.

## Over-constraints removed

1. Liquidity was detected with an older 5-bar fractal. It is now the nearest M1 internal
   swing, consistent with a micro execution model.
2. A sweep required the sweep candle to close back through liquidity. That duplicated the
   job of the later MSS. A wick breach now establishes the sweep; MSS confirms reversal.
3. OB/FVG geometry was forced to overlap the HTF zone. The HTF zone now grants location
   authority; a causal M1 PD array may form just outside the envelope after displacement.
4. The M1 order block used body-only geometry. It now includes the rejection wick:
   BUY OB = low-to-open, SELL OB = open-to-high.
5. Pullback timing was effectively hard-coded to the immediately preceding closed candle.
   It is now bounded by a 12-bar post-MSS window and a 3-bar confirmation window.
6. The final directional candle was also required to hold/re-break the MSS level. That was
   a redundant second MSS. The MSS is confirmed once; the final candle only confirms
   direction after the PD retest.
7. P0 and R1/R2 previously called the same patched builders but diagnostics re-ran a
   separate approximation. All primary cycles now use one scanner.
8. Re-entry now reports an explicit POSITION_UNPROTECTED hold instead of pretending the
   engine is still searching for an M1 pattern.

## Model 1 — production contract

Zone interaction -> micro liquidity sweep -> nearest M1 micro MSS -> causal OB or FVG ->
bounded retest -> latest closed directional M1 candle -> common safety/risk gates -> entry.

The confirmation must be current (latest closed M1), which prevents restart/re-attach
from chasing an old completed pattern.

## Model 2 — production contract

Directional real-body M1 engulfing with zone interaction in the most recent six M1 bars.
It runs in parallel and cannot be blocked by an incomplete Model 1 chain.

## Hard gates intentionally retained

- Cloud execution authority / active thesis ownership
- Demo/paper-only account guard
- Contract parity and immediate pre-order parity revalidation
- Spread guard
- M15 accepted invalidation / lifecycle truth
- Valid target in trade direction
- Full institutional-zone buffered stop
- Actual-entry minimum RR
- Context/grade thesis risk budget and broker-valid lot sizing
- P0/R1/R2 thesis budget cap
- Existing position must be flat or protected before R1/R2

These are risk/safety gates, not pattern-recognition filters.

## Change-control rule

Future primary-entry changes should modify the unified scanner and its regression tests as
one contract. Do not add an independent dashboard detector or a model-specific hidden
confirmation layer.
