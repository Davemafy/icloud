# Dynamic Continuation Re-Zoning v6.5.21

PAPER / DEMO ONLY.

## Why this exists

The 16 September 2026 XAUUSD sell expansion showed two separate truths:

1. A historically valid countertrend demand zone can remain structurally recorded after it has become a poor execution priority.
2. After a large directional displacement, waiting only for the original remote HTF supply/demand can miss a nearer institutional continuation retracement.

This release separates historical zone truth from current execution relevance.

## Execution-map rules

- D1 remains directional context.
- A recent H1/H4 BOS displacement aligned with D1 can open dynamic continuation re-zoning.
- A fresh displacement FVG is a retracement reference only. FVG alone cannot manufacture a zone.
- The retracement reference must have nearby structural H1/H4/D1 BSL for SELL or SSL for BUY.
- The structural liquidity is centered inside the tactical core with buffer on both sides.
- Core and envelope widths use the existing V659 source-timeframe professional geometry.
- The existing 50-pip distal sweep reserve remains mandatory.
- A dynamic continuation candidate may be A+ through one mitigation or A through a second qualified mitigation; three-plus mitigations are WATCH-only.
- A nearer dynamic continuation primary may replace a remote same-direction primary only when it is materially nearer by at least 0.35 H1 ATR and the remote primary is not already INTERACTING or M1_READY.
- An already-acquired thesis is protected. Dynamic re-zoning cannot steal its execution ownership.
- M1 confirmation remains mandatory. Re-zoning never sends an order.

## Countertrend-zone relevance

During an aligned directional expansion:

- A countertrend zone is removed from the current execution map only after genuine exhaustion at three or more core touches.
- It is not deleted from historical lifecycle truth.
- A strong second-touch institutional source may remain A grade and retain reduced-risk execution eligibility.
- B+ is WATCH / research context only and cannot acquire new execution ownership.
- Fresh A/A+ opposing reversal locations remain visible; countertrend classification changes risk, not structural grade.

## Continuation sequence

D1 context -> fresh H1/H4 BOS displacement -> FVG/retest reference -> structural BSL/SSL attached -> liquidity-centered professional core -> retracement -> M1 sweep -> MSS/BOS -> displacement -> dealing range -> OTE/PD-array -> PAPER execution.

## Protected components

- Sequence EA remains v3.26.
- MT5 stable package remains 6.3.7.
- No spread limit was changed.
- No risk-management or order-management path was changed.
- Equal highs/equal lows remain liquidity objects only and cannot create zones by themselves.
