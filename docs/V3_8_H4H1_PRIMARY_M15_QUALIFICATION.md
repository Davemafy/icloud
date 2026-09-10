# v3.8 H4/H1 primary-zone architecture

## Objective

Create institutional intraday/scalp zones from H4/H1 supply-demand/POI structure without turning M15 into an execution delay.

## Timeframe roles

- D1: macro structure and external liquidity context.
- H4: primary institutional supply/demand / POI authority.
- H1: primary intraday supply/demand / POI authority and preferred H4 refinement.
- M15: one-time zone-quality evidence only.
- M1: sole live execution authority.

## Zone-generation rule

M15 cannot create a standalone execution zone. Candidate price boundaries must originate from H4 or H1 observed OHLC displacement origins. Preferred candidate order is:

1. H4 POI refined by overlapping/adjacent same-side H1 POI (`H4>H1`).
2. Clean H1 POI with acceptable H4 context.
3. Compact H4-only POI when it remains reachable and narrow enough for intraday risk.

Remote/wide swing POIs are removed by ATR-relative distance and width filters.

## M15 qualification rule

While the cloud is constructing the zone, M15 may add quality evidence from:

- same-side M15 displacement origin overlapping the H4/H1 POI;
- M15 structural alignment;
- relevant M15 equal-liquidity at/near the POI;
- mitigation/rejection/premium-discount evidence available in supplied history.

This evidence is frozen into the zone grade/confluences at analysis time.

**Once the zone is published, M15 has no further veto or gating role.** The system must not wait for a new M15 candle close, displacement, engulf, CHoCH, MSS or confirmation before M1 execution.

## Live execution rule

When price reaches an authorized published A/A+ zone, the existing Sequence EA may immediately evaluate M1:

`Sweep -> M1 MSS/CHoCH + genuine displacement -> Fibonacci -> fresh M1 OB/BB/FVG -> controlled pullback/confirmation -> entry -> structural SL/liquidity targets -> BE -> dynamic trail`

B+ stays watch-only unless explicitly enabled.
