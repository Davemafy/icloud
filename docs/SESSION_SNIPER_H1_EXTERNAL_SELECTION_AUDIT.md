# Session Sniper — disputed nearest downside H1 source (15 Oct 2026)

**Status: OPEN RESEARCH DEFECT — not validated or fixed in execution code.** Preserve Sequence EA 3.78 and already-running Session Sniper v0.15; current v0.16 remains a draft candidate.

## Evidence supplied by trader

TradingView XAUUSD H1 screenshot (different data source/time-axis from MT5 unless proven otherwise) highlights:
- Reference low on annotated chart around **4145.195** (MT5 v0.15 on-chart reference about **4145.10**).
- Lower boundary of a manually drawn FVG at **4139.760**, upper vicinity about **4145.195**.
- Deeper apparent H1 swing low at **4131.585**.
- MT5 v0.15 information panel previously reported downside `SWING 4144.41`, disputed as a genuine H1 external swing.

These levels are **research examples from screenshots**, not hard-coded trading parameters, validated broker prices or guaranteed unmitigated locations.

## Verified static source behavior in v0.16

`LoadReferenceCandle` currently:
1. Treats a local low as an eligible H1 swing when it has just one neighboring H1 bar on either side and is below the reference low.
2. Selects the numerically closest such low; it does not reject a pivot that was subsequently swept / consumed by later bars.
3. Locates still-partly-unfilled H1 bullish FVGs, ranks by the **nearest still-unfilled proximal** edge, and also records the distal bottom separately.
4. Selects between candidates by proximal level vs swing level; does **not** rank by the trader's requested **FVG distal bottom**.
5. Does not emit all rejected/candidate levels and rejection reasons in a comparable source-time audit.

Thus a `4144.41` one-bar dip can be chosen by the current algorithm even when the trader regards `4131.585` as the meaningful confirmed swing. There is no screenshot-only proof that `4139.760` was unfilled *as of the completed reference* on the broker feed.

## Proposed professional correction (requires staged strategy-logic review)

- Explicitly define a qualified *external* H1 swing: at least two completed neighbors on each side, H1 wick extrema, known by reference formation and not swept afterward through the decision cutoff.
- Handle tied highs/lows consistently, H1 candle close timestamps, broker vs TradingView symbol specifications, and missing/stale H1 data.
- Detect the actual three-candle H1 FVG, audit both **proximal** and **distal** boundaries, exclude fully filled/consumed gaps, calculate any partial remainder using only historical bars closed by the current session's reference end.
- If the business rule is the **FVG distal/bottom as the external sweep objective**, rank the unfilled FVG by that sweep boundary against the qualified unswept H1 swing low. Mark the winning *source, price, source H1 open/close, remaining unfilled range, and rejection reason of alternatives*.
- The closest **eligible** item wins (not always the closest nominal price). For example, if broker-verified 4139.760 remains a qualifying FVG bottom and 4131.585 is an unswept H1 swing low, the former is closer to reference low 4145.195. If the FVG was fully filled or invalid, the latter is a candidate only if its swing and unswept checks pass.
- Never force one of those screenshot prices. If there is no eligible external H1 candidate, fail closed (`DATA_INCOMPLETE` or `NO_QUALIFIED_EXTERNAL`) instead of inventing a liquidity line.

## Required tests before changing entry triggers

Synthetic H1 datasets testing single-bar shallow lows, 2+2 external swing, previously swept swing, FVG with no / partial / full fill, both candidates with different relative distances, missing H1 candles, reference-date consistency, DST boundaries, and independent London/NY clocks. Historical market replay must compare old vs proposed trigger frequency, false sweeps, outcomes and drawdown. MetaEditor 0-error/0-warning compilation and demo-session verification are mandatory before installation.

**No change to execution gate, 70/30 management, risk, /mt5/plan, or stable Institutional Sequence.**
