# Trade Zone V6.4 — ML Data Foundation

## Purpose

V6.4 creates a no-future-leakage dataset for later offline ML training. It is **shadow/data only**. No ML output can place trades, change lots, move stops, select a target, or bypass the deterministic SMC/ICT/regime/risk gates.

Feature contract: `V6_4_MLF1`

Data contract: `V6_4_ML_DATA_FOUNDATION_SHADOW_ONLY`

## Two-layer observations

### 1. Cloud zone/thesis observations

Every scheduled/manual analysis rebuilds the deterministic HTF candidates from the current snapshot and freezes observations for:

- `ZONE_ORIGINAL_THESIS`
- `ZONE_FLIP_HYPOTHESIS`

Both eligible and rejected candidates are retained. The dataset therefore contains examples the existing system did **not** choose, reducing selection bias.

### 2. MT5 execution observations

The authenticated `/mt5/feedback` endpoint accepts `event=ML_CANDIDATE`. The `details` object is validated as `MLCandidateTelemetry`.

Example payload:

```json
{
  "ts": 1789300000,
  "event": "ML_CANDIDATE",
  "analysis_id": "A_...",
  "zone_id": "Z_...",
  "price": 4350.25,
  "details": {
    "source": "MT5_EXECUTION",
    "source_version": "3.23",
    "model": "MOMENTUM_PULLBACK",
    "direction": "BUY",
    "eligible": false,
    "rejection_reasons": ["RESUMPTION_NOT_CONFIRMED"],
    "entry_price": 4350.25,
    "stop_price": 4347.80,
    "target1": 4354.00,
    "target2": 4358.50,
    "atr": 2.10,
    "regime": "TREND",
    "features": {
      "displacement_atr": 1.12,
      "pullback_fraction": 0.44,
      "zone_recently_touched": 1,
      "spread_points": 24
    }
  }
}
```

The current cloud foundation is ready to ingest this stream. Sequence-EA candidate telemetry should be enabled only after its MetaEditor candidate passes compile/DEMO validation.

## Frozen features

`ml_candidates.features` is written once using `INSERT OR IGNORE`. Later labeling never rewrites the feature packet.

The feature sanitizer strips obvious post-event fields supplied by MT5, including keys containing:

- `future_`
- `label`
- `outcome`
- `realized`
- `final_`
- `closed_profit`
- `mfe`
- `mae`
- `tp_hit`
- `sl_hit`

Targets and stops are permitted because they are known at candidate time and are stored separately from realized labels.

## Labels

Each later market snapshot updates only `ml_outcomes`.

Labels include:

- directional return at 15m / 60m / 240m
- ATR-normalized return at the same horizons
- maximum favorable/adverse excursion
- MFE/MAE in R when a valid stop distance exists
- TP1/TP2/TP3 first observed closed-M15 touch timestamps
- SL first observed closed-M15 touch timestamp
- first-barrier result

When TP1 and SL both appear inside the same closed M15 bar, the first barrier is `AMBIGUOUS_SAME_M15_BAR`. The system does not manufacture intrabar sequencing.

The M15 bar containing the candidate timestamp is skipped because part of that candle existed before the feature cutoff.

## Training readiness

Default label horizon: 24 hours.

Default baseline experiment threshold: 1,000 resolved candidates.

This is a **minimum engineering threshold**, not proof that 1,000 observations are statistically sufficient for a production model. Before V6.5 model training, inspect class balance and sample size separately by:

- execution model
- direction
- regime
- session
- grade
- original vs flip branch
- eligible vs rejected

## Export

```bash
python -m app.ml_export --status-only
python -m app.ml_export --out tradezone_ml_dataset.csv
```

CSV prefixes:

- `f__*` — frozen candidate-time features
- `meta__*` — collection metadata
- `label__*` — later labels

Raw core columns such as direction, entry, stop, target, eligibility, result and horizon outcomes remain first-class columns.

## V6.5 hand-off

V6.5 should train offline only. Recommended sequence:

1. logistic-regression baseline
2. gradient-boosted tree candidate (CatBoost/LightGBM/XGBoost)
3. probability calibration
4. chronological walk-forward validation
5. shadow live scoring with **no execution authority**
6. only consider ML gating after material out-of-sample improvement is demonstrated
