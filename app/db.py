from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Optional

from .config import SETTINGS
from .models import Analysis, MarketSnapshot, Feedback, Heartbeat

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
    return db


def init_db() -> None:
    with _lock, connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS analyses(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, analysis_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, ai_ok INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, event TEXT NOT NULL, analysis_id TEXT, zone_id TEXT, price REAL, details TEXT);
        CREATE TABLE IF NOT EXISTS heartbeat(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, ea TEXT, version TEXT, symbol TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL);
        """)


def save_snapshot(s: MarketSnapshot) -> None:
    with _lock, connect() as db:
        db.execute("INSERT INTO snapshots(ts,payload) VALUES(?,?)", (s.sent_at, s.model_dump_json()))
        db.execute("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT 6)")


def latest_snapshot() -> Optional[MarketSnapshot]:
    with _lock, connect() as db:
        row = db.execute("SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    return MarketSnapshot.model_validate_json(row[0]) if row else None


def save_analysis(a: Analysis) -> None:
    with _lock, connect() as db:
        db.execute("INSERT OR REPLACE INTO analyses(ts,analysis_id,payload,ai_ok) VALUES(?,?,?,?)", (a.generated_at, a.analysis_id, a.model_dump_json(), int(a.ai_approved)))


def latest_analysis(ai_required: bool = False) -> Optional[Analysis]:
    q = "SELECT payload FROM analyses" + (" WHERE ai_ok=1" if ai_required else "") + " ORDER BY id DESC LIMIT 1"
    with _lock, connect() as db:
        row = db.execute(q).fetchone()
    return Analysis.model_validate_json(row[0]) if row else None


def save_feedback(f: Feedback) -> None:
    with _lock, connect() as db:
        db.execute("INSERT INTO feedback(ts,event,analysis_id,zone_id,price,details) VALUES(?,?,?,?,?,?)", (f.ts,f.event,f.analysis_id,f.zone_id,f.price,f.details))


def save_heartbeat(h: Heartbeat) -> None:
    with _lock, connect() as db:
        db.execute("INSERT INTO heartbeat(ts,ea,version,symbol,payload) VALUES(?,?,?,?,?)", (h.ts,h.ea,h.version,h.symbol,h.model_dump_json()))
        db.execute("DELETE FROM heartbeat WHERE id NOT IN (SELECT id FROM heartbeat ORDER BY id DESC LIMIT 20)")


def audit(ts: int, action: str, details: str) -> None:
    with _lock, connect() as db:
        db.execute("INSERT INTO audit_log(ts,action,details) VALUES(?,?,?)", (ts,action,details[:5000]))
