# Session Sniper Standalone v0.13 — London + New York

**Status:** DEMO/PAPER research candidate only.

This standalone EA does **not** replace, modify, or share execution state with the current Institutional SMC Sequence EA 3.78.

## Session reference clocks

Both reference candles are defined in the session's own local timezone and converted to broker-server time automatically:

- London: 08:00-09:00 Europe/London local time, including UK daylight-saving changes.
- New York: 08:00-09:00 America/New_York local time, including US daylight-saving changes.
- New York cash-open context remains 09:30 America/New_York local time.

The EA must not permanently hard-code Nigerian clock times.

## Nearest H1 external-reference rule

After the 08:00-09:00 reference candle closes, the EA evaluates the upside and downside independently.

For each side it compares:

1. the nearest confirmed H1 swing high or swing low outside the session range; and
2. the nearest valid H1 fair value gap whose still-unfilled portion remains outside that side of the session range.

Whichever eligible structure is spatially nearest to the relevant session high/low becomes the selected external reference.

For an FVG, distance is measured to the nearest still-unfilled proximal edge. A fully filled FVG is not eligible. A partially filled FVG may remain eligible using the proximal edge of the remaining unfilled portion. If a qualifying swing lies inside the selected FVG, the EA records the level as FVG+SWING confluence.

The chart marks the selected external reference. When an FVG wins, both its remaining proximal edge and distal edge are marked.

## M1 execution contract

A reference touch does not create an entry by itself.

The required sequence remains:

1. completed session reference candle;
2. price trades through the relevant session high/low and reaches the selected nearest H1 external reference;
3. later CLOSED M1 reclaim of the swept session side;
4. CLOSED M1 displacement through the stored micro swing/MSS level;
5. causal breaker/value-origin identification;
6. breaker-body retest;
7. CLOSED directional M1 confirmation from the retest;
8. spread and structural-stop checks;
9. actual-entry R:R to the opposite reference side of at least 2.0;
10. then the 70/30 execution bundle may open.

There is no engulfing-only shortcut and no breakout chase.

## Lifecycle

There is no arbitrary 11:30 cutoff and no 30-minute sweep/MSS/retest timeout.

A developing setup remains valid until it is structurally consumed, a trade is opened, or the next local 08:00 reference lifecycle replaces it.

## Risk and management

- DEMO account required.
- Hedging-mode MT5 account required.
- Base risk default: 0.25%.
- New York entries before the 09:30 New York cash open use the configured 0.50 risk multiplier.
- 70% leg takes profit at the session 0.50 midpoint.
- 30% runner has no hard TP.
- After the midpoint is reached, the runner trails one-way behind confirmed protected M1 structure.
- Stop-after-first-winning-trade defaults to false so London and New York are not disabled merely because the 70% leg closes profitably.

## Isolation

The EA keeps a distinct magic number, state machine, journal, and files under TradeZone/SessionSniper. It has no current Cloud plan dependency and does not modify the stable Sequence 3.78 installation.
