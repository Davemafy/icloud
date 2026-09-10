# Institutional SMC Cloud v3.7 — Intraday/Scalp Institutional Zones

GitHub/Railway-ready cloud service for the demo/paper Institutional SMC project.

## What changed in v3.7

- Trading profile is now `INTRADAY_SCALP`.
- D1/H4 remain mandatory institutional context but are no longer exported as default distant swing-entry zones.
- H1 is the parent intraday framework; M15 supplies/refines actionable reaction locations.
- H1 displacement origins are preferentially refined to nested/adjacent M15 origins (`H1>M15`).
- Nearby standalone M15 displacement origins can become continuation or reversal/transition candidates.
- Candidate zones must pass ATR-relative distance and width filters, keeping the M1 chart focused on session-reachable locations.
- M15 equal-liquidity areas remain B+ watch zones by default.
- Counter-H1 reversal scalps require a fresh M15 transition plus supportive DXY to reach A grade; M1 reversal displacement is raised.
- DXY D1/H4/H1 remains fully included.

## Historical sync retained from v3.6.1

- DXY H4 is now mandatory in protocol-v3 full-history and live updates, with its own ATR(14) and structural bias.
- DXY implication is conservative: H4 and H1 must agree before the deterministic layer marks DXY as supporting or conflicting.
The MT5 bridge and cloud now separate **heavy historical context** from **lightweight live updates**.

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
- The deterministic engine uses the long history for context, but the actionable zone map is now H1/M15-focused for intraday/scalp execution.
- M1 remains the sole execution authority. `PAPER_ONLY=true` remains mandatory in this build.

## Railway deployment

1. Connect this repository to the existing Railway service.
2. Attach a Railway volume at `/data`.
3. Add variables from `.env.example` in Railway Variables and keep `PAPER_ONLY=true`.
4. Set `DATABASE_PATH=/data/smc_cloud.db`.
5. Deploy. The Dockerfile starts Uvicorn on Railway's injected `$PORT`.
6. Healthcheck path: `/health`.
7. Keep the current Railway HTTPS base URL in both MT5 EAs.
8. `CLOUD_EA_API_KEY` in Railway must exactly match `CloudApiKey` in both MT5 EAs.

The Dockerfile copies `docs/SMC_FRAMEWORK_V3_FULL.md`; this file is required by the AI analyst prompt.

## MT5 bridge

Compile and attach `InstitutionalSMC_DataBridge_v1_21_HistorySync_DXYH4.mq5` once on XAUUSD. Set:

- `CloudBaseUrl` = Railway base HTTPS URL
- `CloudApiKey` = same as Railway `CLOUD_EA_API_KEY`
- `DxySymbol` = broker's exact DXY symbol (currently `DXYUSD` in the demo terminal)
- `LiveUploadSeconds` = 60
- `SessionSyncLeadMinutes` = 10
- `PostNewsCooldownMinutes` = same value as the cloud `NEWS_POST_COOLDOWN_MINUTES`

DXY D1/H4/H1 are included in both `FULL_HISTORY` and `LIVE_UPDATE` payloads, with ATR(14) on each timeframe. On startup, expect a `FULL_HISTORY reason=BOOTSTRAP` upload. Normal minutes should show `LIVE_UPDATE reason=LIVE`. Around a session boundary expect `FULL_HISTORY reason=PRE_SESSION:...`; after a qualifying news cooldown expect `FULL_HISTORY reason=POST_NEWS:...`.

## Local test

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

Run locally:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
