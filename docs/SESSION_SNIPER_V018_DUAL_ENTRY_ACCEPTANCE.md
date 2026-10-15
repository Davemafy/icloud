# Session Sniper v0.18 — exact London H1 reference + dual M1 execution

**Candidate only: NOT yet compiled in MetaEditor, installed, backtested or proven in live demo execution.** This is a replacement design for the *faulty active v0.15*, not a proposal to continue treating v0.15 as a validated trading strategy. Older source files remain as reproducibility/archive artifacts only, not recommended execution versions.

## User acceptance criteria

1. **One exact hourly candle**: London **09:00–10:00 Europe/London local**, NY **08:00–09:00 America/New_York local**. Price H/L comes from all **60 individually present closed M1 broker candles**, strict minute continuity; if a bar is absent the reference fails closed. Midpoint is arithmetic 50% of those exact wick extremes. No stale levels from a prior date. The user's London preference is session-local, not a fixed Nigeria clock.
2. **External source correctness**: BUY selects nearer of eligible, unswept 2+2 H1 pivot low or **bottom/distal** of valid unfilled bullish H1 FVG, both below session low; SELL mirrors with eligible H1 swing high or **top/distal** of bearish unfilled FVG. H1 source candle must have closed before the reference started; fully mitigated or previously swept levels cannot be selected. Audit candidates, winning source, range and source times in read-only state/journal.
3. **Aggressive model**: on a **fully closed M1 candle** which sweeps the selected H1 objective (or after a previously confirmed sweep) and reclaims the relevant session boundary, require bullish/bearish directional body >= 0.50 * M1 ATR, and close in the strongest 35% of its range. No compulsory extra MSS or breaker retest. Trade is allowed only if the common order geometry/SL/spread/2.0 RR/70:30 lot split permits it.
4. **Normal model**: preserve existing sweep -> closed reclaim -> M1 MSS/displacement -> breaker retest -> directional close, plus same execution risk gates.
5. **Execution modes**: AGGRESSIVE_ONLY, NORMAL_ONLY, DUAL_AUTO. DUAL_AUTO tries aggressive on the qualifying closed bar, otherwise normal waits; **only one executed bundle per session**, never two duplicate strategies on the same sweep. Aggressive uses half the base session risk; normal retains the existing base. An aggressive **rejection** must not prevent a later valid NORMAL entry if the session is still eligible.
6. **70%/30%**: existing 70% reference-midpoint TP, 30% trail-only structural runner, identical minimum 1:2 distance-to-reference-low/high check and no arbitrary setup expiry.
7. **Demo safety**: only demo hedging account, no alterations to stable Institutional Sequence EA 3.78, DataBridge 1.59, or stable cloud. Shared account risk enforcement with Sequence is not yet deployed; do not claim total account exposure is coordinated.

## High-value acceptance tests before replacing v0.15

- Reference: supply broker M1 data for the 09:00–10:00 London period and check all 60 bar timestamps and high/low/MID against visual H1. Remove one middle minute: state must report DATA INCOMPLETE, no tradable reference.
- External: replay 2+2 protected swing with/without later sweep, multiple FVG candidates and partial/full mitigation; audit nearest **distal** level. Correct UK/US DST handling, reference date rollover, mixed symbol precision.
- M1 aggressive: same closed M1 bar sweeps H1 and rejects, a following closed bar rejects, unfinished/tiny/doji bars rejected, poor close location rejected, spread-high blocked, 2.0 RR failed, structural stop correctly anchored to sweep wick even without a breaker.
- M1 normal: same successful sequence as prior normal EA, no entering on sweep alone, no premature objective consumption; verify fallback from failed aggressive candidate without duplicate orders.
- Journals: ensure each demo execution is marked AGGRESSIVE or NORMAL with the correct session, stage, risk, split, broker fills, and absence of duplicate positions.
- Run deterministic replay and forward-test comparisons against user's documented **15 Oct 2026 manual SELL** example, separately from manual account P/L. No claims that EA can match the manual fills without tick-level broker replay.

## Release gate

The GitHub automated checks exercise Python/source contracts but do **not compile MQL5**. Actual VPS MetaEditor **0 errors / 0 warnings**, historical Deriv H1/M1 replay, and supervised DEMO trial must pass before installing/running v0.18. If v0.15 has open demo orders, manage/close them safely before detaching; never run two standalone Session Sniper versions at once.

Institutional Sequence 3.78 remains untouched.
