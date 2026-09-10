# Institutional SMC Cloud v3.8.1

**Major-news revalidation:** every high-impact USD news cluster triggers a full-history H4/H1 zone revalidation around T-10 and T+10. New M1 entries are locked between the checkpoints; existing demo positions continue deterministic SL/BE/trailing management. M15 is used only to qualify the published zone and never delays M1 execution afterward.

# Institutional SMC Cloud v3.8 — H4/H1 Primary Zones, M15 Qualification, M1 Execution

GitHub/Railway-ready cloud service for the demo/paper Institutional SMC project.

## What changed in v3.8

- H4 and H1 are now the **primary institutional supply/demand / POI authority** for intraday/scalp zones.
- Same-side H4 + H1 confluence is preferred; H1 is the preferred refinement of a broader H4 POI.
- Clean H1 POIs may qualify independently when H4 context is supportive or non-conflicting.
- Compact H4-only POIs may remain only when they pass intraday ATR-distance and width filters; broad or remote swing-style H4 boxes are not exported as immediate scalp zones.
- M15 no longer creates standalone zones. It is used only to qualify an already-derived H4/H1 POI using observed M15 displacement, structure and liquidity evidence.
- **M15 usage ends when the zone is published.** The live EA never waits for another M15 close, displacement, engulfing candle or confirmation.
- Once price reaches a published A/A+ zone, M1 immediately becomes the sole execution authority: sweep -> MSS/displacement -> Fibonacci -> fresh M1 OB/BB/FVG -> confirmation -> entry -> management.
- D1 remains macro context; DXY D1/H4/H1 remains intermarket context.
- B+ remains watch-only/off by default.
- The Sequence EA v2.10 plan protocol stays compatible; no M15 execution-stage field was added.

## Historical sync retained from v3.6.1

The MT5 bridge and cloud separate **heavy historical context** from **lightweight live updates**.

- XAU D1: ~1 trading year (bridge requests 280 bars)
- XAU H4: ~4 months (600 bars)
- XAU H1: ~4+ weeks (600 bars)
- XAU M15: ~5 trading days (520 bars)
- DXY D1: 280 bars
- DXY H4: ~4 months (600 bars)
- DXY H1: 600 bars
- ATR(14) is sent for every supplied timeframe.
- Current XAU bid/ask, spread in points, spread in price, and point size are sent explicitly.
- MT5 high-impact USD calendar events remain in every snapshot.
- Full history is sent on bridge startup, about 10 minutes before Asia/London/New York, and after the configured high-impact-news cooldown.
- Between those events, the bridge sends only a small live update. The cloud merges it into the last full history before analysis.
- The scheduler refuses to use a previous-session full sync when a fresh session full sync is expected.
- Post-news analysis waits for a full history sync captured after the news cooldown.
- M1 remains the sole execution authority. `PAPER_ONLY=true` remains mandatory in this build.

## Railway deployment

1. Replace the existing private GitHub repository contents with this package and commit/push.
2. Railway should auto-deploy the connected repository.
3. Keep the Railway volume mounted at `/data`.
4. Keep `DATABASE_PATH=/data/smc_cloud.db` and `PAPER_ONLY=true`.
5. Set `TRADING_PROFILE=INTRADAY_HTF_ZONE_M1` (recommended label for this build).
6. Healthcheck path remains `/health`.
7. Keep the same Railway HTTPS base URL and `CLOUD_EA_API_KEY` in both MT5 EAs.

The Dockerfile copies `docs/SMC_FRAMEWORK_V3_FULL.md`; this file is required by the AI analyst prompt.

## MT5 bridge

Continue using `InstitutionalSMC_DataBridge_v1_21_HistorySync_DXYH4.mq5` once on XAUUSD. No bridge change is required for v3.8.

Expected data profile:

- XAU D1/H4/H1/M15
- DXY D1/H4/H1
- ATR(14) per timeframe
- current bid/ask and broker spread
- high-impact USD MT5 calendar events

## Sequence EA

Continue using `InstitutionalSMC_SequenceEA_v2_10_Demo.mq5` on XAUUSD M1. No EA change is required for v3.8.

The execution contract after a published zone is:

`ZONE REACHED -> M1 LIQUIDITY SWEEP -> M1 MSS + DISPLACEMENT -> FIB -> FRESH M1 OB/BB/FVG -> M1 CONFIRMATION -> ENTRY -> SL/TP -> BE -> DYNAMIC TRAIL`

There is **no M15 gate after zone publication**.

## Local test

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

Run locally:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
