from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import SETTINGS
from .db import init_db, save_snapshot, latest_snapshot, save_feedback, save_heartbeat, audit
from .engine import active_plan_text
from .models import MarketSnapshot, Feedback, Heartbeat
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
    return {
        "ok": True,
        "app": SETTINGS.app_name,
        "version": SETTINGS.app_version,
        "protocol": SETTINGS.protocol_version,
        "paper_only": SETTINGS.paper_only,
        "snapshot_ready": bool(s and s.complete()),
        "latest_snapshot": s.sent_at if s else None,
        "active_analysis": a.analysis_id if a else None,
        "scheduler": scheduler_status(),
        "execution_contract": "V6_PRIMARY_REENTRY_FLIP_THESIS_RISK",
        "auth_required": True,
    }


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
    return {"ok": True}


@app.get("/mt5/plan", response_class=PlainTextResponse, dependencies=[Depends(require_api_key)])
def mt5_plan():
    a = active_analysis()
    s = latest_snapshot()
    if a is None:
        return PlainTextResponse("protocol=6\nea_mode=NO_TRADE\nreason=NO_ANALYSIS\n", status_code=200)
    # Live safety guards override carry-forward without deleting the historical plan.
    text = active_plan_text(a, s)
    if s:
        now = int(datetime.now(timezone.utc).timestamp())
        age = now - s.sent_at
        extra = []
        if age > SETTINGS.max_snapshot_age_seconds:
            extra.append("LIVE_SNAPSHOT_STALE")
        if s.spread_points > SETTINGS.max_spread_points:
            extra.append("LIVE_SPREAD_HIGH")
        for n in s.news:
            if n.currency.upper() != "USD" or n.impact.upper() != "HIGH":
                continue
            delta_min = (n.ts - now) / 60.0
            if -SETTINGS.news_post_revalidate_minutes <= delta_min <= SETTINGS.news_entry_lock_minutes:
                extra.append("LIVE_HIGH_IMPACT_USD_LOCK")
                break
        if extra:
            text += "live_block=1\nlive_block_reason=" + ",".join(extra) + "\n"
        else:
            text += "live_block=0\n"
    return text


@app.post("/analysis/run")
async def analysis_run(reason: str = "MANUAL"):
    try:
        a = await run_analysis(reason)
        return a.model_dump()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/analysis")
def analysis():
    a = active_analysis()
    if a is None:
        raise HTTPException(status_code=404, detail="No analysis yet")
    return a.model_dump()


def _dashboard_payload(event: str) -> str:
    try:
        s = latest_snapshot()
        a = active_analysis()
        payload = {
            "event": event,
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "snapshot": s.model_dump() if s else None,
            "analysis": a.model_dump() if a else None,
            "scheduler": scheduler_status(),
        }
    except Exception as exc:
        # Never allow dashboard SSE to die because an optional status component fails.
        payload = {"event": "degraded", "error": f"{type(exc).__name__}:{exc}"}
    return json.dumps(payload, separators=(",", ":"))


@app.post("/dashboard/session")
def dashboard_session():
    # Backward-compatible no-op for older dashboards that ping this endpoint.
    return {"ok": True, "version": SETTINGS.app_version}

@app.get("/dashboard/events")
async def dashboard_events(request: Request):
    async def stream():
        yield f"event: state\ndata: {_dashboard_payload('connected')}\n\n"
        while not await request.is_disconnected():
            await asyncio.sleep(3)
            yield f"event: state\ndata: {_dashboard_payload('tick')}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")
