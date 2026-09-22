from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import SETTINGS
from .dashboard_view import compact_dashboard_html
from .execution_owner_mirror import owner_plan_text, recover_owner_from_sequence_heartbeat
from .db import init_db, latest_heartbeats, latest_snapshot, recent_feedback, save_feedback, save_heartbeat, save_snapshot
from .engine import active_plan_text
from .journal import build_trades, export_csv_text, performance_summary, system_status
from .models import Feedback, Heartbeat, MarketSnapshot
from .mt5_zone_render import mt5_zone_render_text
from .scheduler import scheduler_loop, scheduler_status
from .security import require_api_key
from .service import active_analysis, run_analysis

@asynccontextmanager
async def _lifespan(application: FastAPI):
    init_db()
    task = asyncio.create_task(scheduler_loop(run_analysis))
    application.state.scheduler_task = task
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title=SETTINGS.app_name, version=SETTINGS.app_version, lifespan=_lifespan)
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/", response_class=HTMLResponse)
def home():
    p = STATIC / "index.html"
    if not p.exists():
        return "<h1>Institutional SMC AI Cloud</h1>"
    return compact_dashboard_html(p.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    s = latest_snapshot()
    a = active_analysis()
    sys = system_status()
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
        "execution_contract": "V6_3_SMC_LOCATION_REGIME_MULTIMODEL",
        "journal_sync": "V4_PROVENANCE_EXECUTION_GROUPS",
        "components": sys.get("components", {}),
        "auth_required": True,
    }


@app.post("/market/snapshot", dependencies=[Depends(require_api_key)])
def market_snapshot(s: MarketSnapshot):
    save_snapshot(s)
    return {"ok": True, "complete": s.complete(), "sent_at": s.sent_at}


@app.post("/mt5/heartbeat", dependencies=[Depends(require_api_key)])
def heartbeat(h: Heartbeat):
    save_heartbeat(h)
    restored = recover_owner_from_sequence_heartbeat(h)
    return {"ok": True, "owner_mirror_restored": restored}


@app.post("/mt5/feedback", dependencies=[Depends(require_api_key)])
def feedback(f: Feedback):
    # Stamp the cloud runtime that actually ingested this lifecycle event. Do not
    # reinterpret MT5-history recovery runtime versions as original execution
    # versions; provenance stays explicit in the stored payload.
    event = str(f.event or "").upper()
    if event in {"ENTRY_OPENED", "POSITION_MARK", "POSITION_EXIT", "TP_HIT", "SL_HIT", "TRADE_CLOSED"}:
        raw = f.details
        if isinstance(raw, dict):
            details = dict(raw)
        else:
            try:
                parsed = json.loads(str(raw or ""))
                details = parsed if isinstance(parsed, dict) else {}
            except Exception:
                details = {}
        if details.get("recovered_from_mt5_history"):
            details.setdefault("recovery_cloud_version", SETTINGS.app_version)
        else:
            details.setdefault("execution_cloud_version", SETTINGS.app_version)
        details.setdefault("cloud_ingest_version", SETTINGS.app_version)
        f = f.model_copy(update={"details": details})
    save_feedback(f)
    return {"ok": True, "journal_event": True, "journal_sync": "v4_provenance"}


def _append_multimodel_plan(text: str, a) -> str:
    policy = a.execution_policy if a else {}
    mm = policy.get("multi_model", {}) if isinstance(policy, dict) else {}
    regime = mm.get("regime", {}) if isinstance(mm, dict) else {}
    models = mm.get("models", {}) if isinstance(mm, dict) else {}
    params = mm.get("parameters", {}) if isinstance(mm, dict) else {}
    rules = mm.get("rules", {}) if isinstance(mm, dict) else {}

    def flag(name: str) -> str:
        return "1" if bool(models.get(name, False)) else "0"

    extra = {
        "execution_contract_v63": str(mm.get("contract", "V6_3_SMC_LOCATION_REGIME_MULTIMODEL")),
        "analysis_reason": str(mm.get("analysis_reason", "")),
        "market_regime": str(regime.get("name", "UNKNOWN")),
        "market_regime_direction": str(regime.get("direction", "NEUTRAL")),
        "market_regime_confidence": str(regime.get("confidence", 0.0)),
        "market_volatility_ratio": str(regime.get("volatility_ratio", 0.0)),
        "market_efficiency": str(regime.get("efficiency", 0.0)),
        "vwap_proxy": str(regime.get("vwap_proxy", 0.0)),
        "model_ict_sniper": flag("ict_sniper"),
        "model_ict_deep_reentry": flag("ict_deep_reentry"),
        "model_momentum_pullback": flag("momentum_pullback"),
        "model_vwap_proxy_reclaim": flag("vwap_proxy_reclaim"),
        "model_opening_range_retest": flag("opening_range_retest"),
        "model_accepted_zone_flip": flag("accepted_zone_flip"),
        "model_order_flow_imbalance": flag("order_flow_imbalance"),
        "alt_primary_requires_zone_interaction": "1" if rules.get("alternative_primary_requires_recent_zone_interaction", True) else "0",
        "momentum_retrace_min": str(params.get("momentum_retrace_min", 0.30)),
        "momentum_retrace_max": str(params.get("momentum_retrace_max", 0.60)),
        "vwap_band_atr": str(params.get("vwap_band_atr", 0.15)),
        "opening_range_minutes": str(params.get("opening_range_minutes", 30)),
        "alt_model_risk_multiplier": str(params.get("alternate_model_risk_multiplier", 0.75)),
    }
    return text + "".join(f"{k}={v}\n" for k, v in extra.items())


@app.get("/mt5/plan", response_class=PlainTextResponse, dependencies=[Depends(require_api_key)])
def mt5_plan():
    a = active_analysis()
    s = latest_snapshot()
    if a is None:
        return PlainTextResponse("protocol=6\nea_mode=NO_TRADE\nreason=NO_ANALYSIS\n", status_code=200)
    text = _append_multimodel_plan(active_plan_text(a, s), a)
    text += owner_plan_text(int(datetime.now(timezone.utc).timestamp()))
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
        text += ("live_block=1\nlive_block_reason=" + ",".join(extra) + "\n") if extra else "live_block=0\n"
    return text


@app.get("/mt5/zones", response_class=PlainTextResponse, dependencies=[Depends(require_api_key)])
def mt5_zones():
    return PlainTextResponse(mt5_zone_render_text(active_analysis()), status_code=200)


@app.post("/analysis/run")
async def analysis_run(reason: str = "MANUAL"):
    try:
        return (await run_analysis(reason)).model_dump()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/analysis")
def analysis():
    a = active_analysis()
    if a is None:
        raise HTTPException(status_code=404, detail="No analysis yet")
    return a.model_dump()


def _detail_value(raw):
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except Exception:
        return text


def _selected_zone(a):
    """Return the selected public plan or M1-ready execution zone."""
    if a is None or not a.zones or not a.selected_zone_id:
        return None
    for z in a.zones:
        if z.zone_id == a.selected_zone_id:
            return z
    return None


def _readiness_prefix(z) -> str:
    if z is None:
        return ""
    method = str(z.core_method or "")
    return method.split("|", 1)[0] if "|" in method else method


def _event_status(events: list[dict], zone_state: str, readiness: str) -> str:
    names = [str(x.get("event", "")).upper() for x in events]
    if "TRADE_CLOSED" in names:
        return "CLOSED"
    if any(x in names for x in ("TP_HIT", "SL_HIT", "POSITION_EXIT")):
        return "MANAGING"
    if "ENTRY_OPENED" in names or "POSITION_MARK" in names:
        return "IN TRADE"
    if "FAILED_FLIP_CANDIDATE" in zone_state or any("FLIP_CANDIDATE" in n for n in names):
        return "FLIP CANDIDATE"
    if any(any(k in n for k in ("MSS", "BOS", "DISPLACEMENT", "SWEEP")) for n in names):
        return "M1 CONFIRMING"
    if readiness == "M1_READY":
        return "M1 READY"
    if readiness == "INTERACTING":
        return "INTERACTING"
    if readiness == "ARMED":
        return "ARMED"
    if not zone_state:
        return "WAITING"
    return "PLANNED"


def _sequence_reconciled_status(base_status: str, sequence_debug: dict) -> str:
    """Human execution status reconciled against live Sequence EA truth.

    HTF/M1 handoff is macro authority only. A live Sequence micro-gate remains
    authoritative for whether a new paper entry is still waiting, held, sent,
    or already being managed.
    """
    status = str(base_status or "WAITING")
    seq = sequence_debug or {}
    online = bool(seq.get("online"))
    open_positions = int(seq.get("open_positions") or 0)

    # Fresh Sequence truth is authoritative for an actively managed campaign.
    # A closed sibling leg must not make the whole journal read CLOSED while
    # another MT5 position is still open.
    if online and open_positions > 0:
        return "IN TRADE"

    terminal = {"CLOSED", "MANAGING", "IN TRADE", "FLIP CANDIDATE"}
    if status in terminal:
        return status

    if not online:
        return "SEQUENCE OFFLINE" if status == "M1 READY" else status

    authority = str(seq.get("authority") or "NONE")
    stage = str(seq.get("gate_stage") or "UNKNOWN").upper()
    reason = str(seq.get("gate_reason") or "").upper()

    if authority == "NONE":
        return "WAITING FOR SEQUENCE AUTHORITY" if status == "M1 READY" else status
    if stage == "ORDER_SENT":
        return "ORDER SENT"
    if stage in {"REENTRY_CONFIRMATION", "HANDOFF_CONFIRMATION"}:
        return "WAITING FOR M1 VALUE REACTION"
    if stage == "TARGET" and "MIN_RR_NOT_MET" in reason:
        return "ENTRY BLOCKED: MIN RR"
    if stage == "TARGET" and "POST_HANDOFF_OBJECTIVE_ALREADY_TRADED" in reason:
        return "ENTRY BLOCKED: OBJECTIVE ALREADY TRADED"
    if stage == "THESIS" and "REENTRY_LIMIT_REACHED" in reason:
        return "THESIS ENTRY LIMIT REACHED"

    if (
        stage in {"VALUE", "VALUE_PD_ARRAY", "FLIP_VALUE_PD_ARRAY"}
        or "WAITING_FOR_VALID_VALUE" in reason
        or "WAITING_FOR_PULLBACK" in reason
    ):
        return "WAITING FOR VALUE"
    if stage in {"SWEEP", "FLIP_SWEEP"}:
        return "WAITING FOR SWEEP"
    if stage in {"MSS_BOS", "FLIP_MSS_BOS"}:
        return "WAITING FOR MSS/BOS"
    if stage in {"DISPLACEMENT", "FLIP_DISPLACEMENT"}:
        return "WAITING FOR DISPLACEMENT"
    if stage in {"SAFETY", "RISK", "TARGET", "DUPLICATE", "AUTHORITY", "DATA", "MARKET", "BAR"}:
        return "EXECUTION HOLD"

    return "M1 SEQUENCE ACTIVE"


def _sequence_debug_snapshot() -> dict:
    now = int(datetime.now(timezone.utc).timestamp())
    rows = latest_heartbeats(30)
    hb = next((x for x in rows if str(x.get("ea") or "") == "InstitutionalSMC_SequenceEA"), None)
    if hb is None:
        return {
            "online": False,
            "version": "",
            "authority": "NONE",
            "gate_stage": "OFFLINE",
            "gate_reason": "NO_SEQUENCE_HEARTBEAT",
            "candidate_model": "NONE",
            "gate_age_seconds": None,
        }
    payload = hb.get("payload") if isinstance(hb.get("payload"), dict) else {}
    details = dict(payload.get("details") or {}) if isinstance(payload, dict) else {}
    gate_ts = int(details.get("gate_ts") or 0)
    return {
        "online": now - int(hb.get("ts") or 0) <= 45,
        "version": str(hb.get("version") or ""),
        "authority": str(details.get("execution_authority") or "NONE"),
        "gate_stage": str(details.get("gate_stage") or "UNKNOWN"),
        "gate_reason": str(details.get("gate_reason") or ""),
        "candidate_model": str(details.get("candidate_model") or "NONE"),
        "last_execution_model": str(details.get("last_execution_model") or ""),
        "gate_ts": gate_ts,
        "gate_age_seconds": max(0, now - gate_ts) if gate_ts else None,
        "plan_valid": bool(details.get("plan_valid")),
        "analysis_id": str(details.get("analysis_id") or ""),
        "zone_id": str(details.get("zone_id") or ""),
        "primary_entries": int(details.get("primary_entries") or 0),
        "reentries": int(details.get("reentries") or 0),
        "flip_primary_entries": int(details.get("flip_primary_entries") or 0),
        "flip_reentries": int(details.get("flip_reentries") or 0),
        "open_positions": int(details.get("open_positions") or 0),
        "restart_safe": bool(details.get("restart_safe")),
        "owner_mirror_active": bool(details.get("owner_mirror_active")),
        "owner_mirror_zone_id": str(details.get("owner_mirror_zone_id") or ""),
        "execution_handoff_ts": int(details.get("execution_handoff_ts") or 0),
    }


def _journal_target_progress(a, z) -> dict:
    if a is None or z is None:
        return {"next_open": None, "remaining": [], "completed": [], "scope": "NONE"}

    targets = [
        float(z.original_target1 or 0.0),
        float(z.original_target2 or 0.0),
        float(z.original_target3 or 0.0),
    ]
    targets = [x for x in targets if x > 0]
    meta = dict((a.execution_policy or {}).get("active_thesis") or {})
    is_owner = bool(
        meta.get("locked")
        and str(meta.get("owner_zone_id") or "") == z.zone_id
        and str(meta.get("direction") or "") == z.original_direction.value
    )
    if not is_owner:
        # These are map/plan objectives only. Calling target1 the "next open
        # thesis objective" before ownership exists makes the dashboard look as
        # if a live thesis is already active. Keep the ladder visible, but do not
        # publish an active-thesis objective until a handoff actually owns it.
        return {
            "next_open": None,
            "remaining": targets,
            "completed": [],
            "scope": "PLAN",
        }

    best = float(meta.get("best_price") or 0.0)
    remaining: list[float] = []
    completed: list[float] = []
    for idx, target in enumerate(targets, start=1):
        hit_at = int(meta.get(f"target{idx}_hit_at") or 0)
        crossed = bool(
            best > 0
            and (
                (z.original_direction.value == "SELL" and best <= target)
                or (z.original_direction.value == "BUY" and best >= target)
            )
        )
        (completed if hit_at or crossed else remaining).append(target)

    return {
        "next_open": remaining[0] if remaining else None,
        "remaining": remaining,
        "completed": completed,
        "scope": "ACTIVE_THESIS",
    }


def _journal_snapshot():
    a = active_analysis()
    s = latest_snapshot()
    z = _selected_zone(a)
    readiness = _readiness_prefix(z)
    all_events = recent_feedback(500)
    analysis_id = a.analysis_id if a else ""
    zone_id = z.zone_id if z else ""

    if z:
        current_events = [
            e for e in all_events
            if (not analysis_id or not e.get("analysis_id") or e.get("analysis_id") == analysis_id)
            and (not e.get("zone_id") or e.get("zone_id") == zone_id)
        ][:80]
    else:
        current_events = []

    for e in current_events:
        e["details"] = _detail_value(e.get("details", ""))

    zone = None
    if z:
        zone = {
            "zone_id": z.zone_id,
            "direction": z.original_direction.value,
            "flip_direction": z.flip_direction.value,
            "setup_type": z.setup_type,
            "source_tf": z.source_tf,
            "grade": z.grade.value,
            "state": z.state.value,
            "readiness": readiness,
            "core_low": z.core_low,
            "core_high": z.core_high,
            "core_method": z.core_method,
            "zone_low": z.zone_low,
            "zone_high": z.zone_high,
            "touch_count": z.touch_count,
            "confluences": z.confluences,
            "independent_confluence_count": z.independent_confluence_count,
            "invalidation_level": z.invalidation_level,
            "invalidation_rule": z.invalidation_rule,
            "clear_run": z.clear_run,
            "dxy_support": z.dxy_support,
            "original_target1": z.original_target1,
            "original_target2": z.original_target2,
            "original_target3": z.original_target3,
            "original_runner": z.original_runner,
            "flip_target1": z.flip_target1,
            "flip_target2": z.flip_target2,
            "flip_target3": z.flip_target3,
            "flip_runner": z.flip_runner,
        }

    checks = {
        "fresh_zone": bool(z and z.touch_count <= 1),
        "liquidity_in_marked_zone": bool(z and "LIQUIDITY_IN_MARKED_ZONE" in set(z.confluences)),
        "two_plus_confluences": bool(z and z.independent_confluence_count >= 2),
        "clear_run": bool(z and z.clear_run > 0),
        "m15_zone_healthy": bool(z and z.state.value in {"ACTIVE", "FLIP_ACTIVE"}),
        "grade_executable": bool(z and z.grade.value in {"A+", "A", "B+"}),
        "m1_handoff_ready": bool(z and readiness == "M1_READY"),
        "live_data_safe": bool(
            s
            and s.spread_points <= SETTINGS.max_spread_points
            and int(datetime.now(timezone.utc).timestamp()) - s.sent_at <= SETTINGS.max_snapshot_age_seconds
        ),
    }
    score = sum(1 for v in checks.values() if v)
    target_progress = _journal_target_progress(a, z)
    sequence_debug = _sequence_debug_snapshot()
    cloud_authority = str(
        dict((a.execution_policy or {}).get("execution_authority") or {}).get("authority") or "NONE"
    ) if a else "NONE"
    sequence_debug["cloud_authority"] = cloud_authority
    sequence_debug["authority_mismatch"] = bool(
        cloud_authority != "NONE"
        and sequence_debug.get("online")
        and str(sequence_debug.get("authority") or "NONE") == "NONE"
    )
    macro_status = _event_status(current_events, z.state.value if z else "", readiness)
    reconciled_status = _sequence_reconciled_status(macro_status, sequence_debug)

    return {
        "paper_only": SETTINGS.paper_only,
        "analysis_id": analysis_id,
        "generated_at": a.generated_at if a else None,
        "overall_bias": a.overall_bias.value if a else "NEUTRAL",
        "primary_liquidity": a.primary_liquidity if a else "",
        "primary_liquidity_context": a.primary_liquidity if a else "",
        "next_open_thesis_objective": target_progress["next_open"],
        "remaining_thesis_targets": target_progress["remaining"],
        "completed_thesis_targets": target_progress["completed"],
        "target_scope": target_progress["scope"],
        "trader_brief": a.trader_brief if a else "",
        "execution_policy": a.execution_policy if a else {},
        "zone": zone,
        "snapshot": {
            "sent_at": s.sent_at,
            "bid": s.bid,
            "ask": s.ask,
            "spread_points": s.spread_points,
            "complete": s.complete(),
        } if s else None,
        "checks": checks,
        "readiness_score": f"{score}/{len(checks)}",
        "macro_status": macro_status,
        "status": reconciled_status,
        "events": current_events,
        "sequence_debug": sequence_debug,
    }


@app.get("/journal/current")
def journal_current():
    return _journal_snapshot()


@app.get("/journal/trades")
def journal_trades(limit: int = 50):
    limit = max(1, min(int(limit), 500))
    return {"items": build_trades()[:limit], "paper_only": SETTINGS.paper_only}


@app.get("/journal/performance")
def journal_performance():
    return performance_summary()


@app.get("/journal/export.csv")
def journal_export():
    return Response(
        content=export_csv_text(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tradezone_paper_journal.csv"},
    )


@app.get("/system/status")
def system_status_endpoint():
    return system_status()


def _dashboard_payload(event: str) -> str:
    try:
        s = latest_snapshot()
        a = active_analysis()
        payload = {
            "event": event,
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "snapshot": s.model_dump() if s else None,
            "analysis": a.model_dump() if a else None,
            "journal": _journal_snapshot(),
            "scheduler": scheduler_status(),
            "system": system_status(),
        }
    except Exception as exc:
        payload = {"event": "degraded", "error": f"{type(exc).__name__}:{exc}"}
    return json.dumps(payload, separators=(",", ":"))


@app.post("/dashboard/session")
def dashboard_session():
    return {"ok": True, "version": SETTINGS.app_version}


@app.get("/dashboard/events")
async def dashboard_events(request: Request):
    async def stream():
        yield f"event: state\ndata: {_dashboard_payload('connected')}\n\n"
        while not await request.is_disconnected():
            await asyncio.sleep(3)
            yield f"event: state\ndata: {_dashboard_payload('tick')}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
