from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import SETTINGS
from .db import init_db, latest_snapshot, recent_feedback, save_feedback, save_heartbeat, save_snapshot
from .engine import active_plan_text
from .journal import build_trades, export_csv_text, performance_summary, system_status
from .models import Feedback, Heartbeat, MarketSnapshot
from .scheduler import scheduler_loop, scheduler_status
from .security import require_api_key
from .service import active_analysis, run_analysis

app = FastAPI(title=SETTINGS.app_name, version=SETTINGS.app_version)
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.on_event("startup")
async def _startup():
    init_db()
    app.state.scheduler_task = asyncio.create_task(scheduler_loop(run_analysis))


@app.on_event("shutdown")
async def _shutdown():
    t = getattr(app.state, "scheduler_task", None)
    if t:
        t.cancel()


@app.get("/", response_class=HTMLResponse)
def home():
    p = STATIC / "index.html"
    return p.read_text(encoding="utf-8") if p.exists() else "<h1>Institutional SMC AI Cloud</h1>"


@app.get("/health")
def health():
    s = latest_snapshot()
    a = active_analysis()
    sys = system_status()
    return {"ok": True, "app": SETTINGS.app_name, "version": SETTINGS.app_version, "protocol": SETTINGS.protocol_version, "paper_only": SETTINGS.paper_only, "snapshot_ready": bool(s and s.complete()), "latest_snapshot": s.sent_at if s else None, "active_analysis": a.analysis_id if a else None, "scheduler": scheduler_status(), "execution_contract": "V6_PRIMARY_REENTRY_FLIP_THESIS_RISK", "journal_sync": "V3_COMPONENT_TRUTH_SAFE_RELOAD", "components": sys.get("components", {}), "auth_required": True}


@app.post("/market/snapshot", dependencies=[Depends(require_api_key)])
def market_snapshot(s: MarketSnapshot):
    save_snapshot(s)
    return {"ok": True, "complete": s.complete(), "sent_at": s.sent_at}


@app.post("/mt5/heartbeat", dependencies=[Depends(require_api_key)])
def heartbeat(h: Heartbeat):
    save_heartbeat(h)
    return {"ok": True}


@app.post("/mt5/feedback", dependencies=[Depends(require_api_key)])
def feedback(f: Feedback):
    save_feedback(f)
    return {"ok": True, "journal_event": True, "journal_sync": "v3"}


@app.get("/mt5/plan", response_class=PlainTextResponse, dependencies=[Depends(require_api_key)])
def mt5_plan():
    a = active_analysis(); s = latest_snapshot()
    if a is None:
        return PlainTextResponse("protocol=6\nea_mode=NO_TRADE\nreason=NO_ANALYSIS\n", status_code=200)
    text = active_plan_text(a, s)
    if s:
        now = int(datetime.now(timezone.utc).timestamp()); age = now - s.sent_at; extra = []
        if age > SETTINGS.max_snapshot_age_seconds: extra.append("LIVE_SNAPSHOT_STALE")
        if s.spread_points > SETTINGS.max_spread_points: extra.append("LIVE_SPREAD_HIGH")
        for n in s.news:
            if n.currency.upper() != "USD" or n.impact.upper() != "HIGH": continue
            delta_min = (n.ts - now) / 60.0
            if -SETTINGS.news_post_revalidate_minutes <= delta_min <= SETTINGS.news_entry_lock_minutes:
                extra.append("LIVE_HIGH_IMPACT_USD_LOCK"); break
        text += ("live_block=1\nlive_block_reason=" + ",".join(extra) + "\n") if extra else "live_block=0\n"
    return text


@app.post("/analysis/run")
async def analysis_run(reason: str = "MANUAL"):
    try: return (await run_analysis(reason)).model_dump()
    except RuntimeError as exc: raise HTTPException(status_code=409, detail=str(exc))


@app.get("/analysis")
def analysis():
    a = active_analysis()
    if a is None: raise HTTPException(status_code=404, detail="No analysis yet")
    return a.model_dump()


def _detail_value(raw):
    if isinstance(raw, dict): return raw
    if raw is None: return ""
    text = str(raw).strip()
    if not text: return ""
    try: return json.loads(text)
    except Exception: return text


def _selected_zone(a):
    if a is None or not a.zones: return None
    if a.selected_zone_id:
        for z in a.zones:
            if z.zone_id == a.selected_zone_id: return z
    return a.zones[0]


def _event_status(events: list[dict], zone_state: str) -> str:
    names = [str(x.get("event", "")).upper() for x in events]
    if "TRADE_CLOSED" in names: return "CLOSED"
    if any(x in names for x in ("TP_HIT", "SL_HIT", "POSITION_EXIT")): return "MANAGING"
    if "ENTRY_OPENED" in names: return "IN TRADE"
    if "FAILED_FLIP_CANDIDATE" in zone_state or any("FLIP_CANDIDATE" in n for n in names): return "FLIP CANDIDATE"
    if any(any(k in n for k in ("MSS", "BOS", "DISPLACEMENT", "SWEEP")) for n in names): return "M1 CONFIRMING"
    return "PLANNED"


def _journal_snapshot():
    a = active_analysis(); s = latest_snapshot(); z = _selected_zone(a); all_events = recent_feedback(500)
    analysis_id = a.analysis_id if a else ""; zone_id = z.zone_id if z else ""
    current_events = [e for e in all_events if (not analysis_id or not e.get("analysis_id") or e.get("analysis_id") == analysis_id) and (not zone_id or not e.get("zone_id") or e.get("zone_id") == zone_id)][:80]
    for e in current_events: e["details"] = _detail_value(e.get("details", ""))
    zone = None
    if z:
        zone = {"zone_id": z.zone_id, "direction": z.original_direction.value, "flip_direction": z.flip_direction.value, "setup_type": z.setup_type, "source_tf": z.source_tf, "grade": z.grade.value, "state": z.state.value, "core_low": z.core_low, "core_high": z.core_high, "core_method": z.core_method, "zone_low": z.zone_low, "zone_high": z.zone_high, "touch_count": z.touch_count, "confluences": z.confluences, "independent_confluence_count": z.independent_confluence_count, "invalidation_level": z.invalidation_level, "invalidation_rule": z.invalidation_rule, "clear_run": z.clear_run, "dxy_support": z.dxy_support, "original_target1": z.original_target1, "original_target2": z.original_target2, "original_target3": z.original_target3, "original_runner": z.original_runner, "flip_target1": z.flip_target1, "flip_target2": z.flip_target2, "flip_target3": z.flip_target3, "flip_runner": z.flip_runner}
    checks = {"fresh_zone": bool(z and z.touch_count <= 1), "two_plus_confluences": bool(z and z.independent_confluence_count >= 2), "clear_run": bool(z and z.clear_run > 0), "m15_zone_healthy": bool(z and z.state.value in {"ACTIVE", "FLIP_ACTIVE"}), "grade_executable": bool(z and z.grade.value in {"A+", "A"}), "live_data_safe": bool(s and s.spread_points <= SETTINGS.max_spread_points and int(datetime.now(timezone.utc).timestamp()) - s.sent_at <= SETTINGS.max_snapshot_age_seconds)}
    score = sum(1 for v in checks.values() if v)
    return {"paper_only": SETTINGS.paper_only, "analysis_id": analysis_id, "generated_at": a.generated_at if a else None, "overall_bias": a.overall_bias.value if a else "NEUTRAL", "primary_liquidity": a.primary_liquidity if a else "", "trader_brief": a.trader_brief if a else "", "execution_policy": a.execution_policy if a else {}, "zone": zone, "snapshot": {"sent_at": s.sent_at, "bid": s.bid, "ask": s.ask, "spread_points": s.spread_points, "complete": s.complete()} if s else None, "checks": checks, "readiness_score": f"{score}/{len(checks)}", "status": _event_status(current_events, z.state.value if z else ""), "events": current_events}


@app.get("/journal/current")
def journal_current(): return _journal_snapshot()

@app.get("/journal/trades")
def journal_trades(limit: int = 50):
    limit = max(1, min(int(limit), 500)); return {"items": build_trades()[:limit], "paper_only": SETTINGS.paper_only}

@app.get("/journal/performance")
def journal_performance(): return performance_summary()

@app.get("/journal/export.csv")
def journal_export(): return Response(content=export_csv_text(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tradezone_paper_journal.csv"})

@app.get("/system/status")
def system_status_endpoint(): return system_status()


def _dashboard_payload(event: str) -> str:
    try:
        s = latest_snapshot(); a = active_analysis()
        payload = {"event": event, "ts": int(datetime.now(timezone.utc).timestamp()), "snapshot": s.model_dump() if s else None, "analysis": a.model_dump() if a else None, "journal": _journal_snapshot(), "scheduler": scheduler_status(), "system": system_status()}
    except Exception as exc:
        payload = {"event": "degraded", "error": f"{type(exc).__name__}:{exc}"}
    return json.dumps(payload, separators=(",", ":"))

@app.post("/dashboard/session")
def dashboard_session(): return {"ok": True, "version": SETTINGS.app_version}

@app.get("/dashboard/events")
async def dashboard_events(request: Request):
    async def stream():
        yield f"event: state\ndata: {_dashboard_payload('connected')}\n\n"
        while not await request.is_disconnected():
            await asyncio.sleep(3); yield f"event: state\ndata: {_dashboard_payload('tick')}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")
