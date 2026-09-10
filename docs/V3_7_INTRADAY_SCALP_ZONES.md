# v3.7 — Intraday / Scalping Zone Engine

The cloud now separates **institutional context** from **actionable intraday location**.

- D1/H4 remain mandatory and are analyzed for external structure, liquidity, premium/discount and directional risk.
- D1/H4 displacement origins are no longer exported directly as default execution zones.
- H1 is the parent intraday framework.
- M15 is the primary actionable reaction/refinement layer.
- H1 displacement origins are preferentially refined to a nested/adjacent M15 origin (`H1>M15`).
- Nearby standalone M15 displacement origins can also become continuation or reversal/transition candidates.
- M15 equal-liquidity areas remain B+ watch zones by default.
- All actionable candidates must fit ATR-relative distance and width caps, preventing remote swing POIs from filling the M1 chart.
- DXY D1/H4/H1 remains an intermarket context layer. H4/H1 agreement is required for deterministic SUPPORTS/CONFLICTS.
- M1 remains the sole execution authority: zone touch alone never enters a trade.

Default profile controls:

```text
TRADING_PROFILE=INTRADAY_SCALP
INTRADAY_MAX_DISTANCE_H1_ATR=2.5
INTRADAY_MAX_DISTANCE_D1_ATR=0.35
INTRADAY_MAX_ZONE_WIDTH_M15_ATR=2.5
INTRADAY_H1_LOOKBACK=180
INTRADAY_M15_LOOKBACK=320
INTRADAY_MAX_CANDIDATES=8
```

The effective maximum distance is volatility-adaptive rather than a fixed dollar amount. The values are configuration defaults for paper/demo validation and can be tuned from observed replay results rather than guessed from one session.
