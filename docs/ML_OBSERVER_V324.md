# Trade Zone Sequence Observer v3.24 — ML Telemetry Candidate

## Status

`v3.24` is a **DEMO/PAPER-only companion observer candidate** for the V6.4 ML Data Foundation. It is not a replacement for the validated Sequence EA v3.23 and it is not listed in the stable MT5 manifest.

Attach v3.24 only to a **second XAUUSD M1 chart** after MetaEditor reports `0 errors, 0 warnings`. Keep v3.23 attached as the execution EA.

## Zero execution authority

The v3.24 event handlers do not call order placement, position modification, position closing, or trade management. `OnTick()` is intentionally empty. Observation runs from a timer so telemetry WebRequests cannot delay the v3.23 execution EA's M1 tick path.

The observer heartbeats as `InstitutionalSMC_MLObserver` rather than `InstitutionalSMC_SequenceEA`, so the runtime truth for the actual execution EA remains v3.23.

## What is observed

The observer evaluates and records candidate-time information for:

- `ICT_SNIPER`
- `ICT_DEEP_REENTRY`
- `MOMENTUM_PULLBACK`
- `VWAP_PROXY_RECLAIM`
- `OPENING_RANGE_RETEST`
- `ACCEPTED_ZONE_FLIP`
- `ACCEPTED_ZONE_FLIP_REENTRY`

It mirrors the v3.23 priority hierarchy when determining whether a candidate would have been eligible:

- primary: ICT → ORB → Momentum → VWAP
- re-entry: ICT → Momentum → VWAP → ORB

It reads v3.23's `TradeZone\\sequence_state.txt` for runtime counters/open-position context. It never changes that file.

## Accepted and rejected observations

All valid patterns are sent. To avoid flooding the cloud with millions of identical negative examples, incomplete/rejected models are sampled round-robin while price is in relevant zone context. `RejectedSampleEveryBars` controls the sampling interval.

Rejection reasons can include:

- `RUNTIME_STATE_UNKNOWN`
- `CLOUD_LIVE_BLOCK:<reason>`
- `RISK_GUARD_BLOCK`
- `CLOUD_MODEL_NOT_ALLOWED`
- `LOCAL_REGIME_NOT_ALLOWED`
- `EXECUTION_PATH_NOT_ACTIVE`
- `HIGHER_PRIORITY_MODEL_AVAILABLE`
- `PATTERN_NOT_COMPLETE`
- `ENTRY_NOT_AT_VALUE`

## Frozen candidate features

Packets use the existing authenticated `POST /mt5/feedback` channel with `event=ML_CANDIDATE` and feature contract `V6_4_MLF1`.

Candidate features include the execution role, model, direction, cloud/local regime, spread, zone proximity, zone interaction, pattern validity, priority blocking, VWAP proxy context, efficiency, volatility ratio, structural levels, displacement metrics and the current v3.23 runtime counters.

The feature cutoff timestamp is the observation time after the closed M1 bar is available. The M1 bar-open timestamp is stored separately as `closed_m1_bar_open_ts`; it is not incorrectly used as the feature cutoff after the bar has completed.

## Local observer state

v3.24 writes read-only observer truth to:

`MQL5/Files/TradeZone/ml_observer_state.txt`

Important fields:

- `version=3.24`
- `mode=SHADOW_OBSERVATION_ONLY`
- `execution_authority=0`
- `packets_sent`
- `post_errors`
- current analysis/zone/regime

## Validation / promotion rule

1. Compile v3.24 and all helper includes with MetaEditor.
2. Require `0 errors, 0 warnings`.
3. Do not change `mt5/stable/manifest.json` during candidate validation.
4. Attach to a second DEMO XAUUSD M1 chart only.
5. Confirm the Experts log prints the shadow-only startup message.
6. Confirm `ml_observer_state.txt` reports `execution_authority=0`.
7. Confirm the cloud ML dataset receives `source=MT5_EXECUTION`, `source_version=3.24` observations.
8. Only after observation validation should any packaging decision be made. Stable execution remains v3.23 unless separately approved.
