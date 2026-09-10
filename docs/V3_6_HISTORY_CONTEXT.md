# v3.6.1 Historical Context / Session Sync — DXY H4

## Data flow

```text
MT5 DataBridge v1.21
  ├─ startup/restart ───────────── FULL_HISTORY (BOOTSTRAP)
  ├─ ~10 min before session ───── FULL_HISTORY (PRE_SESSION:<name>)
  ├─ after high-impact cooldown ─ FULL_HISTORY (POST_NEWS:<event>)
  └─ normal minute ────────────── LIVE_UPDATE (32 recent bars/TF + quote/spread/ATR/news)

Railway Cloud v1.6.1
  FULL_HISTORY + latest LIVE_UPDATE
               ↓ merge by candle timestamp
        ANALYSIS_CONTEXT
               ↓
 deterministic candidate map (observed OHLC only)
               ↓
 AI selects/rejects/downgrades candidates
               ↓
 validated plan / zones
               ↓
 MT5 M1 Sequence EA (sole execution authority)
```

## Full historical profile

| Market | TF | Bridge request | Intended context |
|---|---:|---:|---|
| XAU | D1 | 280 bars | about one trading year |
| XAU | H4 | 600 bars | about four months |
| XAU | H1 | 600 bars | four+ weeks |
| XAU | M15 | 520 bars | about five trading days |
| DXY | D1 | 280 bars | long intermarket context |
| DXY | H4 | 600 bars | major intermarket structure / transition context |
| DXY | H1 | 600 bars | several weeks |

The cloud refuses protocol-v3 analysis when the advertised full context is below the configured minimums. If MT5 is still downloading history, the bridge retries its startup bootstrap until a full sync succeeds.

## Quote / volatility context

Each payload carries current XAU `bid`, `ask`, `spread_points`, `spread_price`, `point_size`, and ATR(14) for every supplied timeframe. The AI sees these values explicitly. The deterministic validator keeps the spread guard, and the M1 EA remains responsible for actual entry/SL/BE/trailing execution logic.

## Session/news synchronization

The session scheduler does not treat an ordinary LIVE_UPDATE as a replacement for history. Before a scheduled session analysis it requires a FULL_HISTORY snapshot fresh enough for that session. Post-news analysis requires a FULL_HISTORY snapshot captured after the configured news cooldown.

## Railway upgrade

No new service is required. Push the v3.6.1 cloud files to the GitHub repository already connected to Railway. Keep the existing `/data` volume and existing secrets. Add the optional history variables from `.env.example` if you want explicit overrides.

Keep `PAPER_ONLY=true` for this build.
