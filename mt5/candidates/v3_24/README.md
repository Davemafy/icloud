# Sequence Observer v3.24 — candidate only

This folder contains the Trade Zone V6.4 ML telemetry companion EA.

**Do not replace Sequence EA v3.23 with this observer.** v3.23 remains the execution EA. v3.24 is attached only to a second DEMO/PAPER XAUUSD M1 chart after MetaEditor reports **0 errors, 0 warnings**.

Main source:

`InstitutionalSMC_SequenceObserver_v3_24_MLTelemetry_Demo.mq5`

Helper includes:

- `ML24_CoreHelpers.mqh`
- `ML24_ORBAndTelemetry.mqh`
- `ML24_Observe.mqh`
- `ML24_Runtime.mqh`

The main source also requires the existing shared include:

`MQL5/Include/TradeZoneCore/InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5`

The v3.24 event handlers have zero execution authority. `OnTick()` is empty; timer-driven logic only observes candidate patterns and posts `ML_CANDIDATE` packets to the V6.4 cloud. It heartbeats as `InstitutionalSMC_MLObserver` so it cannot masquerade as the execution Sequence EA.

Stable manifest remains on Sequence **3.23** during candidate validation.
