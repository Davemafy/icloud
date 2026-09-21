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
        CREATE TABLE IF NOT EXISTS feedback_event_keys(
            event_uid TEXT PRIMARY KEY,
            first_seen_ts INTEGER NOT NULL,
            event TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS heartbeat(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, ea TEXT, version TEXT, symbol TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS zone_reactions(
            reaction_key TEXT PRIMARY KEY,
            first_analysis_id TEXT,
            latest_analysis_id TEXT,
            first_zone_id TEXT,
            latest_zone_id TEXT,
            direction TEXT NOT NULL,
            source_tf TEXT,
            source_ts INTEGER DEFAULT 0,
            core_low REAL NOT NULL,
            core_high REAL NOT NULL,
            zone_low REAL NOT NULL,
            zone_high REAL NOT NULL,
            grade TEXT,
            status TEXT NOT NULL DEFAULT 'ARMED',
            first_seen_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            core_touched_at INTEGER DEFAULT 0,
            reaction_confirmed_at INTEGER DEFAULT 0,
            target1 REAL DEFAULT 0,
            target2 REAL DEFAULT 0,
            target3 REAL DEFAULT 0,
            runner REAL DEFAULT 0,
            target1_hit_at INTEGER DEFAULT 0,
            target2_hit_at INTEGER DEFAULT 0,
            target3_hit_at INTEGER DEFAULT 0,
            objective_complete_at INTEGER DEFAULT 0,
            invalidated_at INTEGER DEFAULT 0,
            best_price REAL DEFAULT 0,
            mfe_price REAL DEFAULT 0,
            last_reason TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_ts ON feedback(ts);
        CREATE INDEX IF NOT EXISTS idx_feedback_analysis_zone ON feedback(analysis_id, zone_id);
        CREATE INDEX IF NOT EXISTS idx_heartbeat_ts ON heartbeat(ts);
        CREATE INDEX IF NOT EXISTS idx_zone_reactions_status ON zone_reactions(status,last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_zone_reactions_source ON zone_reactions(direction,source_tf,source_ts);
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


def _feedback_event_uid(f: Feedback) -> str:
    raw = f.details
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        return ""

    explicit = str(raw.get("event_uid") or "").strip()
    if explicit:
        return explicit

    event = str(f.event or "").upper()
    deal_id = raw.get("deal_id")
    if deal_id not in (None, "", 0, "0"):
        return f"{event}|DEAL|{deal_id}"

    position_id = raw.get("position_id")
    if event == "TRADE_CLOSED" and position_id not in (None, "", 0, "0"):
        return f"{event}|POSITION|{position_id}"
    return ""


def save_snapshot(s: MarketSnapshot) -> None:
    with _lock, connect() as db:
        db.execute("INSERT INTO snapshots(ts,payload) VALUES(?,?)", (s.sent_at, s.model_dump_json()))
        db.execute("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT 6)")

    # PAPER/DEMO ONLY: persist the institutional lifecycle of a zone after it has
    # interacted, even if a later analysis no longer publishes it as today's
    # primary alert. This is historical state only and grants no execution authority.
    try:
        from .zone_reaction_lifecycle import update_zone_reactions
        update_zone_reactions(s)
    except Exception as exc:
        audit(s.sent_at, "zone_reaction.update.error", f"{type(exc).__name__}:{exc}")

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
    # Register the current institutional zones before the analysis payload is saved.
    # Existing lifecycle records are updated by source identity, never deleted by
    # re-ranking or by a later map choosing another primary.
    try:
        from .zone_reaction_lifecycle import register_analysis_zones
        register_analysis_zones(a)
    except Exception as exc:
        audit(a.generated_at, "zone_reaction.register.error", f"analysis={a.analysis_id} {type(exc).__name__}:{exc}")

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
    # Observer v3.24 is shadow telemetry only. Normalize its context/targets to the
    # current cloud execution contract before the journal or ML dataset sees it:
    # wide envelope = context, tactical core = execution handoff, and every target
    # must sit on the profitable side of the candidate's actual entry.
    if f.event.upper() == "ML_CANDIDATE":
        try:
            from .execution_safety import normalize_candidate_feedback
            f = normalize_candidate_feedback(f, latest_analysis(ai_required=False), latest_snapshot())
        except Exception as exc:
            audit(f.ts, "feedback.execution_safety.error", f"analysis={f.analysis_id} zone={f.zone_id} error={type(exc).__name__}:{exc}")

    event_uid = _feedback_event_uid(f)
    details_text = _details_text(f.details)
    with _lock, connect() as db:
        if event_uid:
            cur = db.execute(
                "INSERT OR IGNORE INTO feedback_event_keys(event_uid,first_seen_ts,event) VALUES(?,?,?)",
                (event_uid, f.ts, f.event),
            )
            if cur.rowcount == 0:
                return
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
