from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Optional, Any

from .config import SETTINGS
from .models import Analysis, MarketSnapshot, Feedback, Heartbeat, MLCandidateTelemetry

_lock = threading.Lock()


def _path() -> str:
    p = SETTINGS.db_path
    parent = os.path.dirname(p)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except PermissionError:
            p = os.path.join(os.getcwd(), "smc_cloud.db")
    return p


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(_path(), timeout=10, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with _lock, connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS analyses(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, analysis_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, ai_ok INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, event TEXT NOT NULL, analysis_id TEXT, zone_id TEXT, price REAL, details TEXT);
        CREATE TABLE IF NOT EXISTS heartbeat(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, ea TEXT, version TEXT, symbol TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_feedback_ts ON feedback(ts);
        CREATE INDEX IF NOT EXISTS idx_feedback_analysis_zone ON feedback(analysis_id, zone_id);
        CREATE INDEX IF NOT EXISTS idx_heartbeat_ts ON heartbeat(ts);
        """)
    if SETTINGS.ml_data_enabled:
        try:
            from .ml_foundation import init_ml_schema
            init_ml_schema()
        except Exception:
            pass


def _details_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return str(value)


def save_snapshot(s: MarketSnapshot) -> None:
    with _lock, connect() as db:
        db.execute("INSERT INTO snapshots(ts,payload) VALUES(?,?)", (s.sent_at, s.model_dump_json()))
        db.execute("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT 6)")
    if SETTINGS.ml_data_enabled:
        try:
            from .ml_foundation import mark_ml_outcomes
            mark_ml_outcomes(s)
        except Exception as exc:
            audit(s.sent_at, "ml.outcome.error", f"{type(exc).__name__}:{exc}")


def latest_snapshot() -> Optional[MarketSnapshot]:
    with _lock, connect() as db:
        row = db.execute("SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    return MarketSnapshot.model_validate_json(row[0]) if row else None


def save_analysis(a: Analysis) -> None:
    with _lock, connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO analyses(ts,analysis_id,payload,ai_ok) VALUES(?,?,?,?)",
            (a.generated_at, a.analysis_id, a.model_dump_json(), int(a.ai_approved)),
        )


def latest_analysis(ai_required: bool = False) -> Optional[Analysis]:
    q = "SELECT payload FROM analyses" + (" WHERE ai_ok=1" if ai_required else "") + " ORDER BY id DESC LIMIT 1"
    with _lock, connect() as db:
        row = db.execute(q).fetchone()
    return Analysis.model_validate_json(row[0]) if row else None


def save_feedback(f: Feedback) -> None:
    details_text = _details_text(f.details)
    with _lock, connect() as db:
        db.execute(
            "INSERT INTO feedback(ts,event,analysis_id,zone_id,price,details) VALUES(?,?,?,?,?,?)",
            (f.ts, f.event, f.analysis_id, f.zone_id, f.price, details_text),
        )

    # V6.4 reuses the authenticated feedback channel for frozen M1 candidate-time
    # telemetry. It is data collection only and never changes execution decisions.
    if SETTINGS.ml_data_enabled and f.event.upper() == "ML_CANDIDATE":
        try:
            raw = f.details
            if isinstance(raw, str):
                raw = json.loads(raw)
            if not isinstance(raw, dict):
                raise ValueError("ML_CANDIDATE details must be an object")
            payload = dict(raw)
            payload.setdefault("ts", f.ts)
            payload.setdefault("analysis_id", f.analysis_id)
            payload.setdefault("zone_id", f.zone_id)
            if not payload.get("entry_price") and f.price:
                payload["entry_price"] = f.price
            telemetry = MLCandidateTelemetry.model_validate(payload)
            from .ml_foundation import ingest_execution_candidate
            ingest_execution_candidate(telemetry)
        except Exception as exc:
            audit(f.ts, "ml.execution.error", f"analysis={f.analysis_id} zone={f.zone_id} error={type(exc).__name__}:{exc}")


def recent_feedback(limit: int = 250) -> list[dict]:
    limit = max(1, min(int(limit), 10000))
    with _lock, connect() as db:
        rows = db.execute(
            "SELECT id,ts,event,analysis_id,zone_id,price,details FROM feedback ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_heartbeat(h: Heartbeat) -> None:
    with _lock, connect() as db:
        db.execute(
            "INSERT INTO heartbeat(ts,ea,version,symbol,payload) VALUES(?,?,?,?,?)",
            (h.ts, h.ea, h.version, h.symbol, h.model_dump_json()),
        )
        db.execute("DELETE FROM heartbeat WHERE id NOT IN (SELECT id FROM heartbeat ORDER BY id DESC LIMIT 100)")


def latest_heartbeats(limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    with _lock, connect() as db:
        rows = db.execute(
            "SELECT ts,ea,version,symbol,payload FROM heartbeat ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        try:
            item["payload"] = json.loads(item["payload"])
        except Exception:
            pass
        out.append(item)
    return out


def audit(ts: int, action: str, details: str) -> None:
    with _lock, connect() as db:
        db.execute("INSERT INTO audit_log(ts,action,details) VALUES(?,?,?)", (ts, action, details[:5000]))
