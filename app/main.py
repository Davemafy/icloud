from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse

from .auth import create_dashboard_session_token, require_admin, require_ea, verify_dashboard_session_token
from .config import SETTINGS, validate_runtime_settings
from .db import DB
from .engine import active_plan_text
from .events import EVENTS
from .models import Heartbeat, InstitutionalAnalysis, ManualNewsTrigger, MarketSnapshot, PlanAck, ReplayRequest, ReplayResult, TradeFeedback
from .news import refresh_news
from .scheduler import mark_manual_analysis_satisfies_session, scheduler_loop, scheduler_status
from .service import (
    apply_live_execution_guards, apply_live_zone_guard, history_status, load_active_execution_analysis, load_analysis_snapshot,
    load_latest_analysis, load_latest_full_snapshot, load_latest_snapshot, persist_snapshot, replay, run_production_analysis,
)


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_runtime_settings()
    task = asyncio.create_task(scheduler_loop())
    DB.audit("service.start", "system", f"env={SETTINGS.app_env} paper_only={SETTINGS.paper_only}")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        DB.audit("service.stop", "system", "shutdown")


app = FastAPI(title="Institutional SMC AI Cloud", version="4.3.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "institutional-smc-ai-cloud",
        "version": "4.3.0",
        "paper_only": SETTINGS.paper_only,
        "ai_enabled": SETTINGS.ai_enabled,
        "ai_configured": any([
            bool(SETTINGS.gemini_api_key),
            bool(SETTINGS.groq_api_key),
            bool(SETTINGS.openrouter_api_key and SETTINGS.openrouter_model),
            bool(SETTINGS.tensormux_base_url and SETTINGS.tensormux_model),
            bool(SETTINGS.openai_api_key),
        ]),
        "ai_provider_order": [x.strip() for x in SETTINGS.ai_provider_order.split(",") if x.strip()],
        "news_provider": SETTINGS.news_provider,
        "timezone": SETTINGS.timezone_name,
        "session_catchup_minutes": SETTINGS.session_catchup_minutes,
        "session_active_recovery": SETTINGS.session_active_recovery,
        "session_snapshot_max_age_seconds": SETTINGS.session_snapshot_max_age_seconds,
        "history_full_max_age_hours": SETTINGS.history_full_max_age_hours,
        "history_protocol": 3,
        "m15_zone_guard": {
            "body_beyond_pct": SETTINGS.m15_zone_guard_body_beyond_pct,
            "min_body_atr": SETTINGS.m15_zone_guard_min_body_atr,
            "two_close_min_body_atr": SETTINGS.m15_zone_guard_two_close_min_body_atr,
            "consecutive_closes": SETTINGS.m15_zone_guard_consecutive_closes,
        },
        "trading_profile": SETTINGS.trading_profile,
        "plan_carry_forward_until_replaced": SETTINGS.plan_carry_forward_until_replaced,
        "plan_refresh_minutes": SETTINGS.plan_valid_minutes,
    }


@app.post("/market/snapshot")
async def ingest_snapshot(snapshot: MarketSnapshot, actor: str = Depends(require_ea)):
    if SETTINGS.paper_only and snapshot.account_mode.upper() not in {"DEMO", "PAPER", "TEST"}:
        raise HTTPException(403, "Cloud is configured paper/demo only")
    sid = await persist_snapshot(snapshot)
    return {
        "accepted": True, "snapshot_id": sid, "generated_at": snapshot.generated_at,
        "snapshot_kind": snapshot.snapshot_kind, "snapshot_reason": snapshot.snapshot_reason,
    }


@app.post("/analysis/run", response_model=InstitutionalAnalysis)
async def analysis_run(reason: str = Query(default="manual"), actor: str = Depends(require_admin)):
    try:
        result = await run_production_analysis(reason=reason)
        # A successful operator-triggered analysis already gives the EA a fresh
        # validated plan, so count it as satisfying the current/upcoming session
        # instead of immediately spending another AI call in the recovery loop.
        mark_manual_analysis_satisfies_session(result, reason)
        await EVENTS.publish("scheduler")
        return result
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/analysis/latest", response_model=InstitutionalAnalysis)
def latest_analysis(actor: str = Depends(require_admin)):
    result = load_latest_analysis()
    if result is None:
        raise HTTPException(404, "No analysis available")
    return result


@app.get("/mt5/plan", response_class=PlainTextResponse)
def mt5_plan(zone_id: str | None = Query(default=None), actor: str = Depends(require_ea)):
    # v4.3: zone maps do not die because a fixed clock elapsed. The latest
    # successful institutional analysis remains active until a newer successful
    # analysis replaces it. Live safety guards can still restrict execution.
    analysis = load_active_execution_analysis()
    if analysis is None:
        return PlainTextResponse("version=3\nea_mode=NO_TRADE\napproved=0\nzone_count=0\nzone_id=NONE\ndirection=NO_TRADE\ngrade=REJECT\nreason=NO_SUCCESSFUL_ACTIVE_PLAN\npaper_only=1\n")
    guarded = apply_live_execution_guards(analysis, load_latest_snapshot())
    return PlainTextResponse(
        active_plan_text(guarded, zone_id, carry_forward=SETTINGS.plan_carry_forward_until_replaced)
    )


@app.post("/mt5/ack")
def mt5_ack(ack: PlanAck, actor: str = Depends(require_ea)):
    DB.add_ack(ack.model_dump(mode="json"))
    DB.audit("mt5.plan_ack", actor, f"analysis={ack.analysis_id} zone={ack.zone_id}")
    return {"accepted": True}


@app.post("/mt5/feedback")
def mt5_feedback(feedback: TradeFeedback, actor: str = Depends(require_ea)):
    DB.add_feedback(feedback.model_dump(mode="json"))
    DB.audit("mt5.feedback", actor, f"signal={feedback.signal_id} event={feedback.event}")
    return {"accepted": True}


@app.post("/mt5/heartbeat")
async def mt5_heartbeat(heartbeat: Heartbeat, actor: str = Depends(require_ea)):
    DB.add_heartbeat(heartbeat.model_dump(mode="json"))
    await EVENTS.publish("heartbeat")
    return {"accepted": True}


@app.post("/news/manual")
async def manual_news(event: ManualNewsTrigger, actor: str = Depends(require_admin)):
    payload = event.model_dump(mode="json")
    payload.update({"released": True, "source": "manual"})
    DB.upsert_news(payload)
    DB.audit("news.manual", actor, f"event={event.event_id} title={event.title}")
    await EVENTS.publish("news")
    # Do not analyze the old pre-release snapshot immediately; scheduler waits for configured cooldown.
    return {"accepted": True, "post_news_reanalysis_after_minutes": SETTINGS.news_post_cooldown_minutes}


@app.post("/news/refresh")
async def news_refresh(actor: str = Depends(require_admin)):
    try:
        events = await refresh_news()
        await EVENTS.publish("news")
        return {"accepted": True, "stored": len(events)}
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/news/reanalyze", response_model=InstitutionalAnalysis)
async def post_news_reanalyze(actor: str = Depends(require_admin)):
    try:
        return await run_production_analysis(reason="manual_post_news")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/replay/run", response_model=ReplayResult)
async def replay_run(req: ReplayRequest, actor: str = Depends(require_admin)):
    return await replay(req.snapshot, req.label)




@app.post("/dashboard/session")
def dashboard_session(request: Request, actor: str = Depends(require_admin)):
    """Bootstrap an HttpOnly dashboard session for EventSource/SSE.

    Browsers cannot attach X-Admin-Key headers to EventSource, so the admin key
    is exchanged for a short-lived signed cookie. The admin key remains only in
    browser local storage and is never placed in an SSE query string.
    """
    token = create_dashboard_session_token()
    response = JSONResponse({"accepted": True, "transport": "sse"})
    response.set_cookie(
        "smc_dashboard_session", token, max_age=43200, httponly=True,
        samesite="strict", secure=(request.url.scheme == "https"), path="/",
    )
    return response


def _dashboard_payload(event_kind: str = "state") -> str:
    state = DB.dashboard_state()
    latest_attempt = load_latest_analysis()
    active = load_active_execution_analysis()
    snap = load_latest_snapshot()
    if latest_attempt is not None:
        state["latest_analysis_attempt"] = latest_attempt.model_dump(mode="json")
    display = active or latest_attempt
    if display is not None:
        state["analysis"] = apply_live_execution_guards(display, snap).model_dump(mode="json")
        now = datetime.now(timezone.utc)
        refresh_due = now > display.valid_until.astimezone(timezone.utc)
        state["plan_lifecycle"] = {
            "status": "CARRY_FORWARD" if (SETTINGS.plan_carry_forward_until_replaced and refresh_due) else "ACTIVE",
            "carry_forward_until_replaced": SETTINGS.plan_carry_forward_until_replaced,
            "refresh_due": refresh_due,
            "refresh_due_at": display.valid_until.isoformat(),
            "active_analysis_id": display.analysis_id,
            "latest_attempt_id": latest_attempt.analysis_id if latest_attempt else None,
            "latest_attempt_ai_used": latest_attempt.ai_used if latest_attempt else None,
        }
    context = load_analysis_snapshot()
    full = load_latest_full_snapshot()
    state["history_context"] = history_status(context)
    state["history_context"]["last_full_sync_at"] = full.generated_at.isoformat() if full else None
    state["history_context"]["last_full_sync_reason"] = full.snapshot_reason if full else None
    state["scheduler"] = scheduler_status()
    state["trading_profile"] = SETTINGS.trading_profile
    state["event_kind"] = event_kind
    state["server_ts"] = datetime.now(timezone.utc).isoformat()
    return json.dumps(state, separators=(",", ":"))


@app.get("/dashboard/events")
async def dashboard_events(request: Request):
    token = request.cookies.get("smc_dashboard_session", "")
    if not verify_dashboard_session_token(token):
        raise HTTPException(401, "Dashboard session required")

    async def stream():
        # Immediate full state on connect, then push a fresh state whenever the
        # MT5 bridge, analysis engine, news layer, heartbeat or scheduler changes.
        yield f"event: state\ndata: {_dashboard_payload('connected')}\n\n"
        async with EVENTS.subscriber() as q:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    kind = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: state\ndata: {_dashboard_payload(kind)}\n\n"
                except asyncio.TimeoutError:
                    # Comment frames keep proxies/connections alive without
                    # forcing a browser-side dashboard refresh.
                    yield f": keepalive {int(datetime.now(timezone.utc).timestamp())}\n\n"

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/dashboard/state")
def dashboard_state(actor: str = Depends(require_admin)):
    state = DB.dashboard_state()
    latest_attempt = load_latest_analysis()
    active = load_active_execution_analysis()
    snap = load_latest_snapshot()
    if latest_attempt is not None:
        state["latest_analysis_attempt"] = latest_attempt.model_dump(mode="json")
    display = active or latest_attempt
    if display is not None:
        state["analysis"] = apply_live_execution_guards(display, snap).model_dump(mode="json")
        now = datetime.now(timezone.utc)
        refresh_due = now > display.valid_until.astimezone(timezone.utc)
        state["plan_lifecycle"] = {
            "status": "CARRY_FORWARD" if (SETTINGS.plan_carry_forward_until_replaced and refresh_due) else "ACTIVE",
            "carry_forward_until_replaced": SETTINGS.plan_carry_forward_until_replaced,
            "refresh_due": refresh_due,
            "refresh_due_at": display.valid_until.isoformat(),
            "active_analysis_id": display.analysis_id,
            "latest_attempt_id": latest_attempt.analysis_id if latest_attempt else None,
            "latest_attempt_ai_used": latest_attempt.ai_used if latest_attempt else None,
        }
    context = load_analysis_snapshot()
    full = load_latest_full_snapshot()
    state["history_context"] = history_status(context)
    state["history_context"]["last_full_sync_at"] = full.generated_at.isoformat() if full else None
    state["history_context"]["last_full_sync_reason"] = full.snapshot_reason if full else None
    state["scheduler"] = scheduler_status()
    state["trading_profile"] = SETTINGS.trading_profile
    return state


@app.get("/scheduler/status")
def get_scheduler_status(actor: str = Depends(require_admin)):
    return scheduler_status()


@app.get("/")
def dashboard():
    if not SETTINGS.dashboard_enabled:
        return JSONResponse({"service": "institutional-smc-ai-cloud", "dashboard": "disabled"})
    return FileResponse(STATIC_DIR / "index.html")
