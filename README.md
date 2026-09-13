# Institutional SMC AI Cloud v6.3

A **DEMO/PAPER-only** XAUUSD architecture that separates **where**, **market regime**, **when**, and **risk**.

- **Cloud / D1-H4-H1:** determines the pre-analysis institutional core from closed data already available at the analysis timestamp. It maps both original rejection and accepted-invalidation/flip possibilities.
- **M15:** qualifies zone health and genuine acceptance beyond the outer envelope.
- **Regime layer:** classifies the current market as `TREND`, `RANGE`, `COMPRESSION`, `EXPANSION`, `EXHAUSTION`, or `UNKNOWN` from volatility and directional-efficiency evidence.
- **M1 execution:** keeps the ICT sniper sequence as first priority, then allows complementary models only when the deterministic regime and HTF-zone rules permit them.
- **Risk manager:** one risk budget per thesis, no averaging down, no SL widening, structure-aware break-even, liquidity partials and slower M5 runner trailing.
- **Historical replay:** pre-generates no-lookahead cloud plans so MT5 Strategy Tester does not depend on live WebRequest/AI calls.

## V6.3 execution model hierarchy

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

V6.3 adds opening analyses aligned to the configured `Africa/Lagos` timezone and Deriv XAUUSD published trading hours:

```text
WEEK_OPEN           Sunday 23:11 WAT
TRADING_DAY_OPEN    Monday-Thursday 23:06 WAT
```

Deriv publishes XAUUSD trading hours as Sunday 22:10 to Friday 20:45 GMT with a Monday-Thursday daily break 20:59-22:05 GMT. The default analysis runs one minute after reopen so the DataBridge can provide a fresh snapshot. The times remain configurable with `WEEK_OPEN_*` and `TRADING_DAY_OPEN_*` environment variables.

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
```

Attach a Railway volume at `/data` if you want SQLite persistence.

## Endpoints

- `GET /health`
- `POST /market/snapshot` — X-API-Key required
- `POST /mt5/heartbeat` — X-API-Key required
- `GET /mt5/plan` — X-API-Key required
- `POST /mt5/feedback` — X-API-Key required
- `POST /analysis/run?reason=MANUAL`
- `GET /analysis`
- `GET /dashboard/events`

If `/mt5/plan` returns 401, the caller did not provide the same `X-API-Key` as `CLOUD_EA_API_KEY`.

## MT5 V6.3 candidate

`mt5/stable/InstitutionalSMC_SequenceEA_v3_23_MultiModel_Demo.mq5` contains the V6.3 complementary execution router. It intentionally remains a **candidate source until it compiles with 0 errors in MetaEditor and passes DEMO/PAPER validation**. Do not promote an uncompiled source to the stable manifest.

The current v3.23 source keeps the validated v3.21 execution/risk core, gives the old ICT primary/re-entry first priority, and attempts a permitted complementary model only if the existing core has no valid signal.

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
2. Confirm `/health` and `/dashboard/events` stay stable with the Windows timezone fallback.
3. Confirm the new `WEEK_OPEN`, `TRADING_DAY_OPEN`, existing session and pre/post-news analysis reasons.
4. MetaEditor: compile the v3.23 candidate with **0 errors**.
5. Compare baseline ICT-only vs ICT + momentum vs ICT + ORB vs ICT + VWAP-proxy vs full multi-model.
6. Strategy Tester forensic replay on representative sessions.
7. Fixed-parameter multi-month test before parameter optimization.
8. Forward-test on DEMO/PAPER_ONLY before any further promotion.
