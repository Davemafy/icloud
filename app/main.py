from __future__ import annotations

import asyncio
import json
import sqlite3
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
from .risk_matrix import execution_grade_eligible, execution_touch_limit, original_risk_pct, zone_risk_context
from .mt5_zone_render import mt5_zone_render_text
from .scheduler import scheduler_loop, scheduler_status
from .security import require_api_key
from .service import active_analysis, run_analysis
from .target_revalidation import target_ladder_truth
from .sniper_contract_parity import evaluate_sequence_parity, plan_contract_from_text, sequence_contract_from_details
from .sniper_validation_ledger import build_validation_ledger, export_validation_csv
from .backtest_jobs import BacktestJobError, run_replay_job, start_replay_job, replay_job_status, replay_job_result

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


def _dashboard_ro_db_path() -> Path:
    """Resolve the deployed SQLite file without taking the process-wide DB lock."""
    configured = Path(SETTINGS.db_path)
    if configured.exists():
        return configured
    fallback = Path.cwd() / "smc_cloud.db"
    return fallback


def _dashboard_ro_connect() -> sqlite3.Connection:
    """Short-timeout, query-only connection used only for human observability.

    It deliberately avoids db.connect(), whose process-wide lock and WAL setup are
    appropriate for normal application writes but must never be able to freeze the
    dashboard. Execution endpoints do not use this connection.
    """
    path = _dashboard_ro_db_path()
    conn = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
        timeout=0.25,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=250")
    return conn


def _dashboard_component_state(desired: str, installed: str, running: str, age: int | None) -> str:
    if age is None or age > 180:
        return "OFFLINE"
    if desired and installed and installed != desired:
        return "UPDATE_PENDING"
    if desired and running and running != desired:
        return "RESTART_REQUIRED"
    if desired and not installed:
        return "CURRENT" if running == desired else "INSTALL_STATUS_UNKNOWN"
    if desired and running == desired:
        return "CURRENT"
    return "UNKNOWN"


def _dashboard_read_only_payload() -> dict:
    """Return enough live truth for the dashboard without touching heavy aggregators."""
    now = int(datetime.now(timezone.utc).timestamp())
    snapshot = None
    analysis = None
    heartbeats: list[dict] = []
    errors: dict[str, str] = {}

    try:
        with _dashboard_ro_connect() as db:
            try:
                row = db.execute("SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
                snapshot = json.loads(row["payload"]) if row else None
            except Exception as exc:
                errors["snapshot"] = f"{type(exc).__name__}:{exc}"

            try:
                row = db.execute("SELECT payload FROM analyses ORDER BY id DESC LIMIT 1").fetchone()
                analysis = json.loads(row["payload"]) if row else None
            except Exception as exc:
                errors["analysis"] = f"{type(exc).__name__}:{exc}"

            try:
                rows = db.execute(
                    "SELECT ts,ea,version,symbol,payload FROM heartbeat ORDER BY id DESC LIMIT 50"
                ).fetchall()
                for row in rows:
                    item = dict(row)
                    try:
                        item["payload"] = json.loads(item.get("payload") or "{}")
                    except Exception:
                        pass
                    heartbeats.append(item)
            except Exception as exc:
                errors["heartbeats"] = f"{type(exc).__name__}:{exc}"
    except Exception as exc:
        errors["database"] = f"{type(exc).__name__}:{exc}"

    manifest = {}
    try:
        manifest = json.loads((ROOT / "mt5" / "stable" / "manifest.json").read_text(encoding="utf-8"))
    except Exception as exc:
        errors["manifest"] = f"{type(exc).__name__}:{exc}"

    def latest_hb(name: str):
        return next((x for x in heartbeats if str(x.get("ea") or "") == name), None)

    def hb_details(row):
        if not isinstance(row, dict):
            return {}
        payload = row.get("payload")
        if not isinstance(payload, dict):
            return {}
        details = payload.get("details")
        return details if isinstance(details, dict) else {}

    bridge_hb = latest_hb("InstitutionalSMC_DataBridge")
    seq_hb = latest_hb("InstitutionalSMC_SequenceEA")
    bridge_d = hb_details(bridge_hb)
    seq_d = hb_details(seq_hb)
    telemetry = bridge_d if bridge_d.get("updater_version") else seq_d

    desired_bridge = str(manifest.get("data_bridge_version") or "")
    desired_seq = str(manifest.get("sequence_ea_version") or "")
    running_bridge = str((bridge_hb or {}).get("version") or "")
    running_seq = str((seq_hb or {}).get("version") or "")
    installed_bridge = str(telemetry.get("installed_bridge_version") or "")
    installed_seq = str(telemetry.get("installed_sequence_version") or "")
    bridge_age = now - int((bridge_hb or {}).get("ts") or 0) if bridge_hb else None
    seq_age = now - int((seq_hb or {}).get("ts") or 0) if seq_hb else None

    # A desired version visibly running in MT5 is authoritative runtime truth even
    # if old installer text on disk has not caught up.
    if desired_bridge and running_bridge == desired_bridge and installed_bridge != desired_bridge:
        installed_bridge = running_bridge
    if desired_seq and running_seq == desired_seq and installed_seq != desired_seq:
        installed_seq = running_seq

    bridge_state = _dashboard_component_state(desired_bridge, installed_bridge, running_bridge, bridge_age)
    seq_state = _dashboard_component_state(desired_seq, installed_seq, running_seq, seq_age)
    restart_safe = str(seq_d.get("restart_safe") or "").strip().lower() in {"1","true","yes","on"}
    open_positions = int(seq_d.get("open_positions") or bridge_d.get("sequence_open_positions") or 0)
    pending_reload = str(telemetry.get("pending_reload") or "").strip().lower() in {"1","true","yes","on"}
    if bridge_state == "CURRENT" and seq_state == "CURRENT":
        pending_reload = False
    restart_manager = (
        "SAFE_RELOAD_ARMED" if pending_reload and restart_safe and seq_age is not None and seq_age <= 45
        else "WAITING_FOR_SAFE_STATE" if pending_reload and seq_hb
        else "FIRST_RELOAD_REQUIRED" if pending_reload
        else "NOT_NEEDED"
    )

    sent_at = int((snapshot or {}).get("sent_at") or 0)
    snapshot_age = now - sent_at if sent_at else None
    spread = (snapshot or {}).get("spread_points")
    alerts = []
    if snapshot is None:
        alerts.append({"level":"RED","code":"NO_SNAPSHOT","message":"No market snapshot could be read by the dashboard."})
    elif snapshot_age is not None and snapshot_age > SETTINGS.max_snapshot_age_seconds:
        alerts.append({"level":"RED","code":"SNAPSHOT_STALE","message":"Market snapshot is stale."})
    if spread is not None and float(spread) > SETTINGS.max_spread_points:
        alerts.append({"level":"AMBER","code":"SPREAD_HIGH","message":"Spread is above the configured demo guard."})
    for key,label,state in (
        ("DATA_BRIDGE","DataBridge",bridge_state),
        ("SEQUENCE_EA","Sequence EA",seq_state),
    ):
        if state == "OFFLINE":
            alerts.append({"level":"RED","code":f"{key}_OFFLINE","message":f"{label} heartbeat is offline/stale."})

    system = {
        "cloud_version": SETTINGS.app_version,
        "paper_only": SETTINGS.paper_only,
        "snapshot_age_seconds": snapshot_age,
        "spread_points": spread,
        "alerts": alerts,
        "healthy": not any(x.get("level") == "RED" for x in alerts),
        "components": {
            "stable_release": str(manifest.get("release") or ""),
            "updater_version": str(telemetry.get("updater_version") or ""),
            "update_result": str(telemetry.get("update_result") or ""),
            "pending_reload": pending_reload,
            "restart_manager": restart_manager,
            "restart_safe": restart_safe,
            "sequence_open_positions": open_positions,
            "components": {
                "data_bridge": {
                    "desired": desired_bridge,
                    "installed": installed_bridge,
                    "running": running_bridge,
                    "status": bridge_state,
                    "heartbeat_age_seconds": bridge_age,
                },
                "sequence_ea": {
                    "desired": desired_seq,
                    "installed": installed_seq,
                    "running": running_seq,
                    "status": seq_state,
                    "heartbeat_age_seconds": seq_age,
                },
            },
        },
    }
    return {
        "ok": True,
        "ts": now,
        "system": system,
        "snapshot": snapshot,
        "analysis": analysis,
        "degraded": bool(errors),
        "errors": errors,
        "source": "SQLITE_QUERY_ONLY_SHORT_TIMEOUT",
    }


@app.get("/dashboard/read-only-state")
def dashboard_read_only_state():
    return _dashboard_read_only_payload()


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


@app.post("/validation/backtest/v659/replay", dependencies=[Depends(require_api_key)])
async def master_sniper_backtest_replay(
    request: Request,
    start: str,
    end: str,
    timezone_name: str = "Africa/Lagos",
    spread_points: float = 16.0,
    point: float = 0.01,
):
    """Authenticated research-only historical replay.

    The uploaded ZIP is processed in a disposable replay database and never
    writes to the live Cloud snapshot/analysis/journal tables.
    """
    payload = await request.body()
    try:
        result = await asyncio.to_thread(
            run_replay_job,
            payload,
            start=start,
            end=end,
            timezone_name=timezone_name,
            spread_points=spread_points,
            point=point,
        )
    except BacktestJobError as exc:
        message = str(exc)
        status = 409 if "already running" in message else 400
        raise HTTPException(status_code=status, detail=message)
    return Response(
        content=result,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=master_sniper_v659_backtest_package.zip"},
    )


@app.post("/validation/backtest/v659/jobs", dependencies=[Depends(require_api_key)])
async def master_sniper_backtest_job_start(
    request: Request,
    start: str,
    end: str,
    timezone_name: str = "Africa/Lagos",
    spread_points: float = 16.0,
    point: float = 0.01,
):
    payload = await request.body()
    try:
        return start_replay_job(
            payload,
            start=start,
            end=end,
            timezone_name=timezone_name,
            spread_points=spread_points,
            point=point,
        )
    except BacktestJobError as exc:
        message = str(exc)
        status = 409 if "already running" in message else 400
        raise HTTPException(status_code=status, detail=message)


@app.get("/validation/backtest/v659/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def master_sniper_backtest_job_status(job_id: str):
    try:
        return replay_job_status(job_id)
    except BacktestJobError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/validation/backtest/v659/jobs/{job_id}/download", dependencies=[Depends(require_api_key)])
def master_sniper_backtest_job_download(job_id: str):
    try:
        result = replay_job_result(job_id)
    except BacktestJobError as exc:
        message = str(exc)
        status = 409 if "not complete" in message else 400
        raise HTTPException(status_code=status, detail=message)
    return Response(
        content=result,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=master_sniper_v659_backtest_package.zip"},
    )


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
    s = latest_snapshot()
    return PlainTextResponse(
        mt5_zone_render_text(active_analysis(), current_mid=(float(s.mid) if s is not None else None)),
        status_code=200,
    )


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


def _zone_note_text(z, prefix: str, default: str = "") -> str:
    if z is None:
        return default
    for note in list(getattr(z, "notes", []) or []):
        text = str(note)
        if text.startswith(prefix):
            return text.split(":", 1)[1] if ":" in text else default
    return default


def _zone_note_int(z, prefix: str, default: int = 0) -> int:
    try:
        return int(float(_zone_note_text(z, prefix, str(default))))
    except (TypeError, ValueError):
        return default


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

    terminal = {"CLOSED", "MANAGING", "IN TRADE"}
    if status in terminal:
        return status

    if not online:
        return "SEQUENCE OFFLINE" if status == "M1 READY" else status

    parity = dict(seq.get("sniper_contract_parity") or {})
    parity_status = str(parity.get("status") or "")
    if status not in terminal and parity_status == "MISMATCH":
        return "ENTRY BLOCKED: SNIPER CONTRACT MISMATCH"
    if status not in terminal and status == "M1 READY" and parity_status in {"UNVERIFIED", "OFFLINE"}:
        return "ENTRY BLOCKED: SNIPER CONTRACT UNVERIFIED"

    authority = str(seq.get("authority") or "NONE")
    stage = str(seq.get("gate_stage") or "UNKNOWN").upper()
    reason = str(seq.get("gate_reason") or "").upper()

    if authority == "NONE":
        return "WAITING FOR SEQUENCE AUTHORITY" if status == "M1 READY" else status
    if stage == "ORDER_SENT":
        return "ORDER SENT"
    if stage in {"ENTRY_CONFIRMATION", "REENTRY_CONFIRMATION", "HANDOFF_CONFIRMATION", "FLIP_CONFIRMATION"}:
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
        parity = evaluate_sequence_parity({}, {}, online=False, open_positions=0)
        return {
            "online": False,
            "version": "",
            "authority": "NONE",
            "gate_stage": "OFFLINE",
            "gate_reason": "NO_SEQUENCE_HEARTBEAT",
            "candidate_model": "NONE",
            "gate_age_seconds": None,
            "sniper_contract_parity": parity,
        }
    payload = hb.get("payload") if isinstance(hb.get("payload"), dict) else {}
    details = dict(payload.get("details") or {}) if isinstance(payload, dict) else {}
    gate_ts = int(details.get("gate_ts") or 0)
    online = now - int(hb.get("ts") or 0) <= 45
    open_positions = int(details.get("open_positions") or 0)

    cloud_contract = {}
    analysis = active_analysis()
    snapshot = latest_snapshot()
    if analysis is not None and snapshot is not None:
        cloud_contract = plan_contract_from_text(active_plan_text(analysis, snapshot))
    sequence_contract = sequence_contract_from_details(details)
    parity = evaluate_sequence_parity(
        cloud_contract,
        sequence_contract,
        online=online,
        open_positions=open_positions,
    )

    return {
        "online": online,
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
        "open_positions": open_positions,
        "restart_safe": bool(details.get("restart_safe")),
        "owner_mirror_active": bool(details.get("owner_mirror_active")),
        "owner_mirror_zone_id": str(details.get("owner_mirror_zone_id") or ""),
        "execution_handoff_ts": int(details.get("execution_handoff_ts") or 0),
        "contract_execution_authority": str(details.get("contract_execution_authority") or ""),
        "contract_parity_status": str(details.get("contract_parity_status") or ""),
        "contract_fingerprint": str(details.get("contract_fingerprint") or ""),
        "sniper_contract_parity": parity,
    }


def _journal_target_progress(a, z) -> dict:
    if a is None or z is None:
        return {"next_open": None, "remaining": [], "completed": [], "scope": "NONE"}

    indexed_targets = [
        (1, float(z.original_target1 or 0.0)),
        (2, float(z.original_target2 or 0.0)),
        (3, float(z.original_target3 or 0.0)),
    ]
    indexed_targets = [(idx, target) for idx, target in indexed_targets if target > 0]
    all_targets = [target for _, target in indexed_targets]
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
            "remaining": all_targets,
            "completed": [],
            "scope": "PLAN",
        }

    authority = str(meta.get("ownership_authority") or "")
    anchor = float(meta.get("ownership_anchor_price") or 0.0)
    prezone_handoff = bool(
        authority == "LIQUIDITY_REVERSAL_HANDOFF"
        and anchor > 0
        and (
            (z.original_direction.value == "SELL" and anchor < float(z.zone_low))
            or (z.original_direction.value == "BUY" and anchor > float(z.zone_high))
        )
    )

    # Only objectives that were still on the profit side when authority began can
    # be called completed by this owner. A SELL target already above a pre-zone
    # handoff anchor (or BUY target already below it) is stale plan context, not a TP.
    live_targets: list[tuple[int, float]] = []
    for idx, target in indexed_targets:
        if anchor <= 0:
            live = True
        elif z.original_direction.value == "SELL":
            live = target < anchor
        else:
            live = target > anchor
        if live:
            live_targets.append((idx, target))

    best = float(meta.get("best_price") or 0.0)
    remaining: list[float] = []
    completed: list[float] = []
    for idx, target in live_targets:
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
        "scope": "PREZONE_HANDOFF" if prezone_handoff else "ACTIVE_THESIS",
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
            "structural_grade": _zone_note_text(z, "structural_grade:", z.grade.value),
            "grade": z.grade.value,
            "current_execution_grade": _zone_note_text(z, "current_execution_grade:", z.grade.value),
            "grade_degrade_reason": _zone_note_text(z, "grade_degrade_reason:", "NONE"),
            "grade_context_model": _zone_note_text(z, "grade_context:", ""),
            "structural_aplus_missing": _zone_note_text(z, "structural_aplus_missing:", "NONE"),
            "structural_a_missing": _zone_note_text(z, "structural_a_missing:", "NONE"),
            "grade_location_score": float(_zone_note_text(z, "grade_location_score:", "0") or 0),
            "grade_source_strength": float(_zone_note_text(z, "grade_source_strength:", "0") or 0),
            "geometry_published_at": _zone_note_int(z, "geometry_published_at:", 0),
            "publication_qualified_mitigations": _zone_note_int(z, "publication_qualified_mitigations:", int(z.touch_count)),
            "publication_raw_core_contacts": _zone_note_int(z, "publication_raw_core_contacts:", int(z.touch_count)),
            "live_core_touched_at": _zone_note_int(z, "live_core_touched_at:", 0),
            "live_core_touch_basis": _zone_note_text(z, "live_core_touch_basis:", "NONE"),
            "live_core_touch_price": float(_zone_note_text(z, "live_core_touch_price:", "0") or 0),
            "publication_execution_status": _zone_note_text(z, "publication_execution_status:", "UNKNOWN"),
            "state": z.state.value,
            "readiness": readiness,
            "core_low": z.core_low,
            "core_high": z.core_high,
            "core_method": z.core_method,
            "zone_low": z.zone_low,
            "zone_high": z.zone_high,
            "touch_count": z.touch_count,
            "qualified_mitigations": _zone_note_int(z, "qualified_mitigations:", int(z.touch_count)),
            "raw_core_touch_episodes": _zone_note_int(z, "raw_core_touch_episodes:", int(z.touch_count)),
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
            "risk_context": zone_risk_context(z),
            "base_risk_pct": original_risk_pct(z),
            "execution_grade_eligible": execution_grade_eligible(z),
        }

    target_truth = (
        target_ladder_truth(a, z, s)
        if a is not None and z is not None and s is not None
        else {
            "status": "UNAVAILABLE",
            "objectives": [],
            "open_targets": [],
            "completed_targets": [],
            "behind_activation_targets": [],
            "authority_safe": False,
            "history_complete": False,
            "remap_required": False,
        }
    )

    checks = {
        "fresh_zone": bool(z and execution_touch_limit(z) >= 0 and z.touch_count <= execution_touch_limit(z)),
        "liquidity_in_marked_zone": bool(z and "LIQUIDITY_IN_MARKED_ZONE" in set(z.confluences)),
        "two_plus_confluences": bool(z and z.independent_confluence_count >= 2),
        "clear_run": bool(z and z.clear_run > 0),
        "m15_zone_healthy": bool(z and z.state.value in {"ACTIVE", "FLIP_ACTIVE"}),
        "grade_executable": bool(z and execution_grade_eligible(z)),
        "target_ladder_phase_valid": bool(
            str(target_truth.get("status") or "") == "PLANNED_NOT_ACTIVATED"
            or bool(target_truth.get("authority_safe"))
        ),
        "m1_handoff_ready": bool(z and readiness == "M1_READY"),
        "live_data_safe": bool(
            s
            and s.spread_points <= SETTINGS.max_spread_points
            and int(datetime.now(timezone.utc).timestamp()) - s.sent_at <= SETTINGS.max_snapshot_age_seconds
        ),
    }
    score = sum(1 for v in checks.values() if v)
    target_progress = _journal_target_progress(a, z)
    # Before a zone activates, its TP ladder remains a forward PLAN. Historical
    # price travel through those future TP prices does not consume the ladder.
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
        "target_revalidation_status": target_truth.get("status"),
        "target_ladder_truth": target_truth.get("objectives") or [],
        "target_open_objectives": target_truth.get("open_targets") or [],
        "target_completed_objectives": target_truth.get("completed_targets") or [],
        "target_behind_activation_objectives": target_truth.get("behind_activation_targets") or [],
        "target_activation_reference": target_truth.get("activation_reference"),
        "target_activation_reference_basis": target_truth.get("activation_reference_basis"),
        "target_history_complete": bool(target_truth.get("history_complete")),
        "target_history_reason": target_truth.get("history_reason"),
        "target_remap_required": bool(target_truth.get("remap_required")),
        "target_authority_safe": bool(target_truth.get("authority_safe")),
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


@app.get("/validation/sniper-ledger")
def sniper_validation_ledger(limit: int = 50):
    return build_validation_ledger(limit)


@app.get("/validation/sniper-ledger.csv")
def sniper_validation_ledger_csv(limit: int = 250):
    return Response(
        content=export_validation_csv(limit),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=master_sniper_validation_ledger.csv"},
    )


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
    """Build dashboard transport without allowing one read-only section to blank the page.

    The dashboard is observational only. Snapshot, analysis, journal, scheduler and
    system-status aggregation are intentionally isolated so a failure in one section
    cannot suppress healthy telemetry from the others. This is especially important
    for the system/version card and mitigation audit during forensic review.
    """
    payload = {
        "event": event,
        "ts": int(datetime.now(timezone.utc).timestamp()),
        "snapshot": None,
        "analysis": None,
        "journal": None,
        "scheduler": None,
        "system": None,
    }
    errors: dict[str, str] = {}

    def capture(name: str, fn):
        try:
            payload[name] = fn()
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}:{exc}"

    capture(
        "snapshot",
        lambda: (lambda s: s.model_dump() if s else None)(latest_snapshot()),
    )
    capture(
        "analysis",
        lambda: (lambda a: a.model_dump() if a else None)(active_analysis()),
    )
    capture("journal", _journal_snapshot)
    capture("scheduler", scheduler_status)
    capture("system", system_status)

    if errors:
        payload["degraded"] = True
        payload["errors"] = errors
    else:
        payload["degraded"] = False

    # default=str is a final read-only transport guard. It must never be able to
    # break execution logic because this payload is dashboard-only.
    return json.dumps(payload, separators=(",", ":"), default=str)


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
