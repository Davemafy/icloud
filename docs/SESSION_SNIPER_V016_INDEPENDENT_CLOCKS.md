# Session Sniper v0.16 — independent session reference clocks

**DEMO/PAPER candidate only.** User-reported manual observations favor the London **09:00–10:00 Europe/London-local** candle. This observation is a research hypothesis, not a validated improvement in expectancy.

## Reference contract

| Session | Local reference | Time zone authority | Nigeria (15 Oct 2026) | Nigeria (2 Nov 2026) |
|---|---|---|---|---|
| London | 09:00–10:00 | Europe/London | 09:00–10:00 WAT | 10:00–11:00 WAT |
| New York | 08:00–09:00 | America/New_York | 13:00–14:00 WAT | 14:00–15:00 WAT |

Session-local dates and UK/US daylight-saving rules determine the broker-time mapping. **These are not fixed Nigeria-local windows.** London moves one hour later in Nigeria when the UK returns to GMT. New York 09:30 cash-open context remains unchanged.

## Changed from v0.15

- Replace shared `InpReferenceHourLocal` and `InpReferenceMinuteLocal` with independent London / New York pairs.
- Set London defaults to **09:00 local**, New York defaults to **08:00 local**.
- Display both session-local reference windows in the chart's read-only information panel.
- Preserve v0.15 source and installed EX5 as rollback; the new installer downloads a distinct v0.16 file.
- No clock-based setup timeout; next local session reference starts a new daily lifecycle as before.

## Trading algorithm unchanged

No modifications to nearest qualifying H1 swing or still-unfilled FVG, reference high/low sweeps, M1 reclaim/MSS/breaker/retest/directional close, structural stop, minimum R:R, 70% midpoint TP, 30% trail-only runner, spread guard, hedging requirement, magic number, or demo-only protection.

No edits to Institutional SMC Sequence EA 3.78, DataBridge 1.59, cloud plan authority, or stable package.

## Validation gate

- GitHub Python/source-contract tests must pass.
- MetaEditor v0.16 compilation must show **0 errors / 0 warnings** (NOT yet verified on VPS).
- Only replace v0.15 after all its open positions have closed; never run v0.15 and v0.16 together. Leave Sequence 3.78 alone.
- Verify London 08:59, 09:30 and 10:01 **London local** during UK summer time; after the UK DST transition in late October, verify the Nigeria display moves one hour later.
- Verify New York 07:59, 08:30 and 09:01 **New York local**, particularly during the US transition in November.
- Before the configured reference, current-day levels must remain unavailable; afterward, compare H/L/MID and H1 external liquidity to closed candles and session-local trading date.
- Maintain separate sample journals and compare 08:00 vs 09:00 London reference variants on the same no-lookahead historical dataset before interpreting reported manual performance.
