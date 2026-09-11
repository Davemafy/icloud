# v4.1 M15 live zone-health guard

H4/H1 remain the primary institutional supply/demand / POI authority. M15 is used once to qualify/refine the H4/H1 zone at analysis time, and M1 remains the sole entry trigger after publication.

The live invalidation guard is intentionally separate from execution confirmation:

- SELL/supply: distal boundary is the published zone high.
- BUY/demand: distal boundary is the published zone low.
- Wick-only penetration is ignored.
- One CLOSED M15 candle blocks the zone for new M1 entries when at least `M15_ZONE_GUARD_BODY_BEYOND_PCT` of the real body is beyond the distal boundary and the body is at least `M15_ZONE_GUARD_MIN_BODY_ATR` x M15 ATR.
- Default values are 60% and 0.40 x ATR.
- Persistence fallback: `M15_ZONE_GUARD_CONSECUTIVE_CLOSES` consecutive M15 closes beyond the boundary invalidate when each body is at least `M15_ZONE_GUARD_TWO_CLOSE_MIN_BODY_ATR` x ATR. Defaults are 2 closes and 0.20 x ATR.
- Existing demo positions are not force-closed by this cloud guard; local M1 EA SL/BE/trailing management continues.
- H1/H4 structural retirement/replacement is handled by the next full session or T-10/T+10 news reanalysis.

This keeps M15 fast enough for intraday zone health without turning M15 back into a second entry gate.
