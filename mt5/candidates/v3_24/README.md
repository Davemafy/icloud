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

## Observer cloud defaults

The observer now exposes its own cloud inputs so a fresh attach does not require retyping the endpoint:

```text
ObserverCloudBaseUrl=https://icloud-production-9111.up.railway.app
ObserverCloudApiKey=123
```

These observer-specific inputs are used for both `/mt5/plan` reads and `/mt5/feedback` / heartbeat posts. The legacy cloud inputs inherited from the shared v3.21 analytical core are not used by the v3.24 observer network path.

The v3.24 event handlers have zero execution authority. `OnTick()` is empty; timer-driven logic only observes candidate patterns and posts `ML_CANDIDATE` packets to the V6.4 cloud. It heartbeats as `InstitutionalSMC_MLObserver` so it cannot masquerade as the execution Sequence EA.

Stable manifest remains on Sequence **3.23** during candidate validation.
