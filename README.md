# Institutional SMC Cloud v4.3 — Carry-Forward Zone Lifecycle

The institutional zone map no longer expires just because `PLAN_VALID_MINUTES` elapsed. That value is now a **refresh target**, not a hard expiry. The newest successful institutional analysis remains the active plan until a newer successful analysis replaces it.

Important safety behavior is preserved:
- Closed-M15 acceptance/mitigation can still invalidate or retire a carried zone immediately.
- Current spread and live-snapshot freshness can block new M1 entries without deleting the zones.
- Current T-10/T+10 high-impact USD news blackout blocks new entries dynamically.
- If a major USD release occurs after the active plan, the zones remain visible but execution stays locked until a successful post-news institutional analysis replaces that pre-news plan.
- When `REQUIRE_AI_FOR_EXECUTION=true`, an AI-unavailable fallback analysis is stored for audit but does **not** evict the previous AI-validated plan. A later successful AI analysis (including an AI NO_TRADE decision) supersedes it.
- Sequence EA v2.12 remains compatible: cloud plan protocol v3 sends `valid_until_epoch=0` while carry-forward is enabled and exposes the former expiry separately as `refresh_due_epoch`.

Recommended Railway setting: `PLAN_CARRY_FORWARD_UNTIL_REPLACED=true`. Keep `PAPER_ONLY=true` during validation.

---

# Institutional SMC Cloud v4.2 — D1/H4/H1 Two-Sided Institutional Day Map

This build realigns zone creation with the original manual prompt: XAU D1, H4 and H1 jointly create the institutional supply/demand map. D1 is a real parent-zone authority, H4/H1 refine the intraday executable boundary, M15 qualifies the zone once and then only monitors zone health, and M1 remains the sole execution authority.

The deterministic engine now searches both sides of XAU and keeps at most one best BUY zone and one best SELL zone when observed evidence exists. On a directional D1/H4/H1 day, the same-direction zone is labelled **CONTINUATION** and the opposite-side institutional zone is labelled **REVERSAL**. On a mixed/neutral top-down day, the sides are labelled transition buy/sell. A missing side is never fabricated.

Preferred zone stacks are `D1>H4>H1`, then `D1>H4`, `H4>H1`, `D1>H1`, then a clean H1-only POI. D1-only broad boxes are context/parent zones and should be refined before M1 execution. DXY D1/H4/H1 remains analysis-only and now grades each BUY/SELL zone against the DXY direction that specifically supports that zone, which is important for reversal setups.

---

# Institutional SMC Cloud v4.1 — M15 Live Zone-Health Guard

This build keeps the v4.0 foundation alignment but changes live zone invalidation for the intraday/scalp profile. H4/H1 still create and qualify the institutional POI; M15 qualification still ends when the zone is published; M1 remains the sole execution trigger.

The live guard is now M15-based so an intraday zone can be blocked before waiting for an H1/H4 close. This is **zone-health monitoring only**, not an extra M15 entry confirmation.

Default invalidation rule for a published XAU zone:
- Wick-only penetration through the distal boundary does **not** invalidate the zone.
- One CLOSED M15 candle invalidates for new M1 entries when at least 60% of its real body is beyond the distal boundary and its real body is at least 0.40 x M15 ATR.
- As a persistence fallback, 2 consecutive CLOSED M15 candles beyond the boundary also invalidate when each has a meaningful body of at least 0.20 x M15 ATR.
- H1/H4 are no longer the live entry-permission gate. Longer-term structural retirement is reassessed by the next full session/news institutional analysis.
- Existing demo positions are not force-closed by this guard; local structural SL, BE and trailing management continue unchanged.

Railway overrides are available with `M15_ZONE_GUARD_BODY_BEYOND_PCT`, `M15_ZONE_GUARD_MIN_BODY_ATR`, `M15_ZONE_GUARD_TWO_CLOSE_MIN_BODY_ATR`, and `M15_ZONE_GUARD_CONSECUTIVE_CLOSES`. Keep `PAPER_ONLY=true` during validation.

# Institutional SMC Cloud v4.0 — Foundation Alignment

This build is a code-level audit/fix against the original manual institutional XAU workflow. It preserves H4/H1 zone authority, one-time M15 qualification and M1-only execution, while closing the main gaps found in v3.8.3.

Key fixes:
- HTF BOS/CHoCH and zone formation use **closed candles only**; the MT5 forming candle can no longer create a false H4/H1 zone.
- H4/H1 displacement zones now prefer the nearest **opposite-colour/base source candle** before the launch instead of blindly treating the immediately previous candle as supply/demand.
- DXY D1 is now a deterministic macro filter on top of DXY H4/H1; a D1 conflict neutralizes the intermarket implication instead of overstating correlation.
- A live CLOSED-M15 zone-health guard blocks new M1 entries when price shows real body acceptance through the distal boundary or the zone becomes over-mitigated. Wick-only penetration is ignored; H1/H4 retirement is reassessed on the next full analysis.
- Actual high-impact USD news objects (time/title/released/actual/forecast/previous) are now included in the AI analysis packet.
- Deterministic feature map now exposes confirmed structure breaks, swing/equal/session/prior-day liquidity, exact FVG ranges, rejection wicks, probable trendline liquidity, broker tick-volume context, compression/expansion hints and XAU psychological levels.
- A large displacement candle alone cannot receive A/A+; it also needs a confirmed structure break and/or same-side FVG before the deterministic grade can remain executable.
- Every zone records the exact source candle time, source candle range, displacement time, structure-break level, FVG range when present, mitigation count, tick-volume ratio, nearby psychological level and exact structural invalidation boundary.
- Targets prefer observed liquidity pools rather than generic range midpoints.
- DXY D1/H4/H1 remains analysis-only and cannot create execution zones.
- T-10/T+10 high-impact-news revalidation and deterministic management of existing demo positions remain intact.

The MT5 plan protocol stays version 3, so Sequence EA v2.12 remains compatible. Keep PAPER_ONLY=true during validation.

# Institutional SMC Cloud v3.8.3

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


## v3.8.2 symbol-integrity hardening

- Data Bridge v1.23 uses explicit `XauSymbol` and `DxySymbol` inputs instead of treating the chart `_Symbol` as XAU.
- The bridge refuses to initialize if attached to a chart other than the configured XAU symbol.
- XAU bid/ask, spread and point size are always read from `XauSymbol`.
- Cloud rejects protocol-v3 MT5 snapshots when XAU and DXY symbol streams collide or when the broker quote is grossly inconsistent with the latest XAU M15 close.
- Keep exactly one Data Bridge instance attached to XAUUSD.


## v3.8.3 XAU-only zones + M1 zone visibility

- DXY D1/H4/H1 remains intermarket analysis context only. It cannot produce or be serialized as a trading zone.
- All published/view/execution zones are explicitly XAUUSD/GOLD zones.
- Use Sequence EA v2.11 ZoneVisibility on XAUUSD M1. It auto-fits the nearest published zone into the chart scale and shows a nearest-zone guide, while still drawing the normal faint blue/red rectangle.
- NO_TRADE caused by a news blackout does not hide an already-published XAU zone; it is displayed as WATCH while new entries remain locked.
