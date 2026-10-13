# Session Sniper Standalone v0.12 — London + New York

**Status:** DEMO/PAPER research candidate only.

This is a new standalone execution family. It does **not** replace, modify, or share execution state with the current Institutional SMC Sequence EA 3.78.

## Core idea

The system trades from one qualified external-liquidity event toward the opposite side of a session reference range.

Each session uses a local **08:00-09:00 reference candle** as its key zone:

- London: 08:00-09:00 Europe/London local time.
- New York: 08:00-09:00 America/New_York local time.
- New York cash-open timing context: 09:30 local.

Session times are converted to broker-server time automatically with UK/US daylight-saving rules. A manual broker UTC offset is available for Strategy Tester.

## Hard execution sequence

A trade is not allowed merely because price touches or breaks the 08:00 range.

1. Reference candle closes.
2. Find the nearest confirmed H1 external swing:
   - BUY candidate requires external SSL below the reference low.
   - SELL candidate requires external BSL above the reference high.
3. Price must sweep **both** the corresponding reference-candle side and that external H1 liquidity.
4. A later CLOSED M1 candle must reclaim the swept reference side.
5. M1 displacement must break a confirmed micro swing (MSS).
6. The engine identifies the last opposite M1 candle as the breaker/value origin.
7. Price must retest the breaker body.
8. A CLOSED directional M1 candle must confirm from the retest.
9. Actual-entry R:R to the opposite reference side must be at least 1:2.
10. Only then may the EA open one position for that session.

There is no engulfing-only shortcut and no direct breakout-candle chase in v0.12.

## Stop contract

The execution stop is structural:

- BUY: below the deeper of the swept external-liquidity extreme and breaker wick, plus broker/spread/ATR safety buffer.
- SELL: above the higher of the swept external-liquidity extreme and breaker wick, plus buffer.

The EA does not force a tight stop to improve R:R. If the structural stop makes R:R unacceptable, the trade is skipped.

## Target and management

- 70% TP leg = 0.50 midpoint of the session reference candle; 30% runner target = opposite side of the session reference candle.
- Minimum actual-entry R:R = 2.0.
- At the 50% midpoint the 70% leg is banked; the remaining 30% runner then trails behind confirmed protected M1 structure and keeps the opposite reference-side TP.
- One 70/30 execution bundle per session.
- Optional daily stop after the first profitable closed Session Sniper trade.

## Risk

Defaults are deliberately conservative for forward research:

- Base risk: 0.25% per qualified trade.
- New York entries before 09:30 local: 50% of base risk.
- Spread guard: 50 points.
- Real accounts are hard-blocked.

## Isolation from the existing system

The standalone EA uses:

- a distinct magic number;
- its own session state machine;
- its own state file under `TradeZone/SessionSniper/`;
- its own CSV research journal;
- no current Cloud map, thesis-owner, P0/R1/R2, or Sequence 3.78 execution authority.

This separation is intentional. We can compare the two systems without contaminating either result set.

## AI layer — intended role

The deterministic sequence above remains the hard execution contract. The AI layer should later act as a **quality supervisor**, not as a rule bypass.

It should score:

- quality and hierarchy of the swept liquidity;
- whether London/NY reference liquidity is clean or already consumed;
- displacement quality;
- reclaim quality;
- session timing;
- available runway to the opposite external objective;
- DXY/macro alignment as confluence only;
- whether a second manipulation leg is still probable.

The AI may return `ALLOW`, `WATCH`, or `BLOCK`, but must never authorize a trade that failed the external sweep, reclaim, MSS, breaker-retest, stop, spread, or minimum-R:R gates.

## Forward-validation plan

Do not merge this into the stable installer yet.

First compile and attach the standalone EA on a separate XAUUSD M1 demo chart. Collect at least 10 London and 10 New York qualified session samples. For every candidate record:

- session reference high/low;
- external H1 liquidity level;
- sweep time and penetration;
- reclaim;
- MSS/displacement;
- breaker retest;
- entry, SL, TP, actual R:R;
- MAE/MFE and result;
- whether the opposite reference side was reached.

Only after that sample should we decide whether to add FVG-based external-liquidity selection, re-entry, partial exits, or cloud AI veto authority.


## v0.12 lifecycle correction

The session setup no longer expires because of an arbitrary clock.

Removed:
- the 11:30 local execution cutoff;
- the 30-minute sweep-to-MSS timeout;
- the 30-minute MSS-to-retest timeout.

The setup remains valid after the 08:00-09:00 reference candle closes until one of these structural events occurs:
- the intended opposite reference-side objective is reached before entry, consuming the opportunity;
- a trade is opened for that session;
- the next local 08:00 reference lifecycle begins.

The 30% runner also has no hard TP. The opposite reference side is telemetry/objective context only; the runner exits through the one-way protected-M1 structural trailing stop or another explicit risk close.
