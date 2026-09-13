# Institutional SMC AI Cloud v6.4

A **DEMO/PAPER-only** XAUUSD architecture that separates **where**, **market regime**, **when**, **risk**, and now **machine-learning data collection**.

- **Cloud / D1-H4-H1:** determines the pre-analysis institutional core from closed data already available at the analysis timestamp. It maps both original rejection and accepted-invalidation/flip possibilities.
- **M15:** qualifies zone health and genuine acceptance beyond the outer envelope.
- **Regime layer:** classifies the current market as `TREND`, `RANGE`, `COMPRESSION`, `EXPANSION`, `EXHAUSTION`, or `UNKNOWN` from volatility and directional-efficiency evidence.
- **M1 execution:** keeps the ICT sniper sequence as first priority, then allows complementary models only when the deterministic regime and HTF-zone rules permit them.
- **Risk manager:** one risk budget per thesis, no averaging down, no SL widening, structure-aware break-even, liquidity partials and slower M5 runner trailing.
- **V6.4 ML data foundation:** freezes candidate-time features, stores both accepted and rejected opportunities, labels outcomes later, and keeps all ML logic in **shadow/data-only mode**.
- **Historical replay:** pre-generates no-lookahead cloud plans so MT5 Strategy Tester does not depend on live WebRequest/AI calls.

## V6.4 ML data foundation

V6.4 does **not** train or deploy a trading model yet. Its purpose is to build a trustworthy dataset before any model is allowed to score setups.

The collector creates two SQLite tables:

- `ml_candidates` — immutable feature packets captured at the decision timestamp.
- `ml_outcomes` — labels and later market outcomes that are updated only after the feature cutoff.

The feature contract is `V6_4_MLF1` and the operating mode is `V6_4_ML_DATA_FOUNDATION_SHADOW_ONLY`.

### What is collected

For cloud-side institutional candidates, V6.4 records both the **original thesis** and the **flip hypothesis**, including candidates that the current rules reject. Features include:

- D1/H4/H1 XAU structure bias and DXY structure bias.
- Zone source timeframe, grade, state, location score, freshness/touch count and confluences.
- Premium/discount and distance-to-zone information normalized by M15 ATR.
- Spread, M15/H1/H4/D1 volatility, regime, efficiency, expansion and VWAP-proxy context.
- London/New York time windows, weekday and scheduled-analysis reason.
- High-impact USD news proximity.
- Which V6.3 execution models were eligible at the feature cutoff.
- AI approval/provider state as context only; AI still does not set prices or risk.

Rejected candidates are intentionally preserved. This is important because training only on trades already selected by the existing strategy would create selection bias.

### Outcome labels

Later market snapshots update a separate outcome record with:

- 15-minute, 60-minute and 240-minute directional returns.
- ATR-normalized horizon returns.
- Maximum favorable excursion and maximum adverse excursion.
- Risk-normalized MFE/MAE when a valid stop distance exists.
- TP1/TP2/TP3 and SL timestamps when those barriers are defined.
- `TP1_BEFORE_SL`, `SL_BEFORE_TP1`, `AMBIGUOUS_FIRST_BARRIER`, or expiry state after the configured label horizon.

If TP1 and SL are both crossed inside the same M15 bar, the label is marked **ambiguous** instead of inventing an intrabar order that the data cannot prove.

### Future-leakage protection

Candidate features are written with `INSERT OR IGNORE`, so the original feature packet is never rewritten later with outcome information. MT5-supplied feature dictionaries also pass through a sanitizer that removes obvious post-event keys such as `future_*`, `label*`, `mfe`, `mae`, `tp_hit`, `sl_hit`, and realized/final outcome fields.

The first partial M15 bar after a candidate is not used for excursion/barrier labeling because its high/low may contain price action from before the candidate timestamp. Labeling begins from later fully closed bars.

### M1 execution telemetry contract

The existing authenticated `/mt5/feedback` channel now accepts an `event` of `ML_CANDIDATE`. Its `details` object is validated as a frozen `MLCandidateTelemetry` packet and stored separately from trade-journal outcomes.

This means future/current Sequence EA candidates can submit **eligible and rejected** ICT, momentum, VWAP-proxy, ORB and flip opportunities without adding a second public authentication mechanism. V6.4 is ready to ingest those M1 packets; the active execution logic remains deterministic and unchanged.

### Dataset export

On the cloud/Railway shell or a local copy of the same database:

```bash
python -m app.ml_export --status-only
python -m app.ml_export --out tradezone_ml_dataset.csv
```

The CSV joins frozen features and later labels. Nested feature keys are flattened with `f__`, metadata with `meta__`, and labels with `label__` prefixes.

The default readiness threshold is 1,000 resolved candidates. Reaching that number means only that baseline ML experiments may begin; it does **not** mean the dataset is automatically sufficient for production trading.

## V6.3 execution model hierarchy retained in V6.4

HTF SMC location remains the authority. The extra models do not create trades in arbitrary parts of the chart and do not bypass spread, news, snapshot, grade, zone-health or thesis-risk guards.

1. **ICT sniper primary** — sweep → MSS/BOS body close → displacement → new dealing range → premium/discount → OTE → fresh PD array → retracement.
2. **ICT deep-value re-entry** — the validated continuation re-entry already in the v3.21 core.
3. **Momentum pullback** — continuation BOS/impulse followed by a controlled 30–60% pullback and directional resumption. Used only in `TREND`/`EXPANSION` regimes.
4. **VWAP-proxy reclaim** — a tick-volume-weighted XAUUSD CFD fair-value proxy used only as a continuation/reclaim tool in a `TREND` regime. It is explicitly **not** represented as centralized COMEX volume.
5. **Opening-range breakout/retest** — London/NY opening-range expansion followed by a retest and directional resumption. Used only in `TREND`/`EXPANSION` regimes.
6. **Accepted-zone flip** — unchanged principle: accepted invalidation creates a candidate only; the opposite trade still requires retest + structure/displacement/value confirmation.

Alternative primary/re-entry signals use a conservative `0.75` risk multiplier until their expectancy is separately validated. Order-flow imbalance is intentionally disabled until an appropriate centralized/market-depth feed is available.

## Scheduled analysis

All existing intraday checkpoints are preserved:

```text
07:50
12:50
15:20
```

Opening analyses remain:

```text
WEEK_OPEN           Sunday 23:11 WAT
TRADING_DAY_OPEN    Monday-Thursday 23:06 WAT
```

High-impact USD pre/post-news re-analysis is also retained.

## Every verified zone still has two branches

A zone is a decision area, not a one-direction prediction.

**Branch A — rejection:** original-direction M1 execution.

**Branch B — accepted invalidation:** the original direction is disabled and the zone becomes only a `FLIP_CANDIDATE`. Invalidation itself is never an opposite entry.

## Pre-analysis core rule

The core can only use information already present on closed D1/H4/H1 candles. Later M1 FVG/OB/displacement may execute the trade but may not retroactively redefine the cloud core.

## Risk defaults (demo starting values)

- Thesis risk: **0.50%** equity.
- Primary allocation: 60% of thesis budget.
- Re-entry 1: 30%.
- Re-entry 2: 10%.
- Alternative-model multiplier: 0.75 of the normal allocation until validated.
- Flip thesis multiplier: 0.75 until historical/forward testing proves equal expectancy.
- Break-even: only after >=1R and fresh M1 structural progress.
- Runner: M5 structure + ATR, not M1 noise.
- Daily lock: 2 thesis-R.

These are test parameters, not guarantees of profitability.

## Windows timezone protection

`tzdata` is included in `requirements.txt`, and the scheduler uses `safe_zoneinfo()`. If a Windows Python installation cannot resolve the IANA key `Africa/Lagos`, the cloud falls back narrowly to fixed UTC+1 `WAT` rather than crashing the scheduler or SSE dashboard.

## Local run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Set environment variables through your shell, `.env` loader, Railway variables, or your process manager. The app intentionally does not include a hidden `.env` parser.

## Railway

Deploy the whole folder. Set at least:

```text
CLOUD_EA_API_KEY=<same secret used by both EAs>
PAPER_ONLY=true
AI_ENABLED=true
REQUIRE_AI_FOR_EXECUTION=true
GEMINI_API_KEY=<your key>
TIMEZONE_NAME=Africa/Lagos
DB_PATH=/data/smc_cloud.db
ML_DATA_ENABLED=true
```

Attach a Railway volume at `/data` if you want the ML dataset and SQLite state to persist across deploys.

## Endpoints

- `GET /health`
- `POST /market/snapshot` — X-API-Key required
- `POST /mt5/heartbeat` — X-API-Key required
- `GET /mt5/plan` — X-API-Key required
- `POST /mt5/feedback` — X-API-Key required; also carries `ML_CANDIDATE` telemetry
- `POST /analysis/run?reason=MANUAL`
- `GET /analysis`
- `GET /dashboard/events`

If `/mt5/plan` returns 401, the caller did not provide the same `X-API-Key` as `CLOUD_EA_API_KEY`.

## MT5 V6.3 candidate

`mt5/stable/InstitutionalSMC_SequenceEA_v3_23_MultiModel_Demo.mq5` contains the V6.3 complementary execution router. It intentionally remains a **candidate source until it compiles with 0 errors in MetaEditor and passes DEMO/PAPER validation**. Do not promote an uncompiled source to the stable manifest.

The stable MT5 execution release is not automatically changed by the V6.4 ML data foundation. The ML collector cannot place orders or modify MT5 risk.

## Backtesting in MT5 Strategy Tester

Export historical CSVs into one folder:

```text
XAU_D1.csv
XAU_H4.csv
XAU_H1.csv
XAU_M15.csv
DXY_D1.csv
DXY_H4.csv
DXY_H1.csv
news.csv
```

Generate timestamped no-lookahead plans with `python -m app.backtest`, copy the generated CSV into MT5 Common Files, set the Sequence EA to `TESTER_FILE`, and run XAUUSD M1 using **Every tick based on real ticks**.

## Validation order

1. Python tests: `pytest -q`.
2. Confirm the cloud deploy reports application version 6.4.0 and remains PAPER_ONLY.
3. Confirm scheduled analyses create `ml.cloud.capture` audit entries.
4. Allow later snapshots to populate 15m/60m/240m labels and MFE/MAE without rewriting frozen features.
5. Export the dataset with `python -m app.ml_export --status-only` and then CSV export.
6. Integrate/validate M1 `ML_CANDIDATE` telemetry before using execution-model data for training.
7. Continue compiling and DEMO-validating the v3.23 multi-model EA separately.
8. Only after a sufficiently large walk-forward dataset exists should V6.5 begin offline baseline model training.
