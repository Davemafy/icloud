# Institutional SMC AI Cloud v6.0

A demo/paper-only XAUUSD architecture that separates **where**, **when**, and **risk**:

- **Cloud / D1-H4-H1:** determines the pre-analysis institutional core using only closed data already available at the analysis timestamp. It maps both original rejection and accepted-invalidation/flip possibilities.
- **M15:** qualifies/health-checks the published zone and confirms genuine acceptance beyond the *outer envelope*. M15 does not delay normal M1 execution.
- **M1 Sequence EA:** determines exact sniper timing using sweep → MSS/BOS body close → displacement → new dealing range → premium/discount → 61.8–78.6 OTE → fresh FVG/OB → retracement.
- **Risk manager:** one risk budget per thesis, no averaging down, no SL widening, structure-aware break-even, liquidity partials and slower M5 runner trailing.
- **Historical replay:** pre-generates no-lookahead cloud plans and lets MT5 Strategy Tester replay the M1 execution engine from file, because Strategy Tester should not depend on live WebRequest/AI calls.

## Important v6 addition: every verified zone has two branches

A zone is a decision area, not a one-direction prediction.

**Branch A — rejection:** original-direction M1 sniper sequence.

**Branch B — accepted invalidation:** the original direction is disabled and the zone becomes only a `FLIP_CANDIDATE`. Invalidation itself is never an opposite entry. The EA must wait for an opposite-side retest, M1 structure shift/displacement, a new dealing range, correct premium/discount OTE and a fresh PD array before the flip entry.

## Pre-analysis core rule

The core can only use information already present on closed D1/H4/H1 candles. Later M1 FVG/OB/displacement may execute the trade but may not retroactively redefine the cloud core. The selector prefers multi-timeframe overlap, correct premium/discount extremity, external liquidity adjacency, freshness and clear run.

## Risk defaults (demo starting values)

- Thesis risk: **0.50%** equity.
- Primary allocation: 60% of thesis budget.
- Re-entry 1: 30%.
- Re-entry 2: 10%.
- Flip thesis multiplier: 0.75 until historical/forward testing proves equal expectancy.
- Break-even: only after >=1R **and** fresh M1 structural progress.
- Runner: M5 structure + ATR, not M1 noise.
- Daily lock: 2 thesis-R.

These are test parameters, not guarantees of profitability.

## Windows timezone fix

`tzdata` is included in `requirements.txt`. The cloud also uses a safe `Africa/Lagos -> UTC+1` fallback, so a missing Windows IANA database cannot crash `scheduler_status()` or the SSE dashboard.

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
GEMINI_MODEL=gemini-3.6-flash
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

If `/mt5/plan` returns 401, the EA's `CloudApiKey` does not exactly match `CLOUD_EA_API_KEY`.

## MT5 files

The MT5 EA files are distributed separately from this cloud repository. Compile them in MetaEditor and require **0 compile errors** before attachment.

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
news.csv             # optional
```

CSV bars need: `ts/open/high/low/close` (optional `tick_volume`). `ts` may be Unix seconds or ISO-8601.

Generate timestamped no-lookahead plans:

```bash
python -m app.backtest \
  --input-dir ./historical \
  --start 2025-01-01T00:00:00+00:00 \
  --end 2026-01-01T00:00:00+00:00 \
  --out SMC_v6_tester_plans.csv
```

Copy that CSV into MT5 **Common Files**, set the Sequence EA to `TESTER_FILE`, and run XAUUSD M1 using **Every tick based on real ticks**. The EA selects only plans whose timestamp is <= Strategy Tester time, preventing future leakage.

## Validation order

1. Python tests: `pytest -q`.
2. MetaEditor: compile both EAs with 0 errors.
3. Local cloud: `/health` and dashboard must remain stable; confirm no `ZoneInfoNotFoundError`.
4. Data Bridge: `/market/snapshot` 200 and `/mt5/heartbeat` 200.
5. Sequence EA: `/mt5/plan` 200, not 401.
6. Strategy Tester forensic replay on ~10 sessions.
7. Three-month fixed-parameter test.
8. 1–2 year test before any parameter optimization.
9. Forward-test on DEMO/PAPER_ONLY.
