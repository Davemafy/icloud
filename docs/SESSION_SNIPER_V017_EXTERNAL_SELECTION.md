# Session Sniper v0.17 — nearest eligible H1 external objective

**Research/demonstration release candidate. Not VPS-compiled or deployed.** User confirms the symmetric rule below. Preserve Institutional Sequence 3.78, DataBridge 1.59 and stable MT5 package; do not merge this trading-logic change before MT5 testing.

## Confirmed trading rule (not hard-coded screenshot prices)

- **BUY:** below the *completed* session reference low, choose whichever is closer to that low:
  - a **confirmed, unswept H1 swing low** (actual H1 wick, 2 complete bars before and 2 after it); or
  - **the bottom of a still-partly-or-fully-unfilled bullish H1 FVG** (the older candle's high in a bullish three-candle displacement).
- **SELL:** above the completed reference high, select whichever is closer:
  - a confirmed, unswept H1 swing high (actual wick, 2+2 pivot); or
  - **the top of a still-unfilled bearish H1 FVG** (the older candle's low in a bearish three-candle displacement).
- Do not use the closest proximal gap edge as the sweep trigger. Both FVG boundaries are retained: a distal sweep objective and a remaining proximal boundary for observation.
- An H1 pivot ceases to be eligible if **any later H1 candle through the pre-reference cutoff** equals or exceeds the swing extreme. FVGs become ineligible when fully filled before or during the 60-minute reference. Partial fills shorten the remainder but leave the true distal target unchanged.
- To prevent hindsight, only H1 candles closed by reference start can *form* a candidate; only subsequent, already-completed H1 candles and the just-closed reference can *mitigate* it. No future candles after reference completion are used to backfill the initial choice.
- Ties at exactly the same objective price select the swing rather than the FVG. If neither candidate exists, no external sweep can authorize an entry. Missing H1 data (fewer than 7 bars) fails closed as `H1_DATA_INCOMPLETE`.
- The chosen **winner and source H1 timestamp**, along with numerical swing/FVG alternatives, appear in the separate `session_journal.csv` `REFERENCE_ARMED` event and state-file `*_candidate_audit` fields. None of these diagnostic fields authorize orders.

Example from trader's H1 screenshot: low near 4145.195, bullish FVG lower edge near 4139.760, deeper swing low around 4131.585. If the FVG was still eligible on the exact broker H1 feed **at reference formation**, its 4139.760 bottom is numerically closer to 4145.195; if filled, the H1 swing 4131.585 is a candidate only if confirmed and still unswept. The earlier 4144.41 is not automatically invalid from a screenshot; it must be tested against the 2+2 pivot and unswept qualification rules. No fixed prices are embedded in the algorithm.

## Preserved invariants

London 09:00–10:00 `Europe/London` and New York 08:00–09:00 `America/New_York` reference clocks remain independent and DST-aware. No arbitrary setup timeout. Post-sweep M1 reclaim → closed MSS/displacement → breaker retest → directional close, minimum 1:2 R:R, 70% midpoint and 30% structural runner, demo-hedging account check, same independent magic 6510010.

## Release gates — still OPEN

1. Static GitHub source-contract and other Python checks pass.
2. MetaEditor compilation on the Deriv demo VPS: 0 errors and 0 warnings, obtain actual log.
3. Backtest/synthetic H1 fixture replay covers shallow 1-bar pivot vs 2+2, unswept vs swept, valid/partially/fully filled bullish and bearish FVGs, and candidates with distinct proximity.
4. Reference clock DST boundaries and missing historical candles checked against closed **broker MT5** H1 candles.
5. Confirm 4144/4139/4131 observed choices on exact timestamped broker H1 data; do not substitute TradingView prices for broker candles.
6. Confirm safe replacement only when old Session Sniper positions are flat; run just one Session Sniper version at a time.
7. Independently validate broker account exposure safeguards before permitting both EAs to enter together on the same demo account.
