from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import SETTINGS


class Database:
    def __init__(self, path: Optional[str] = None):
        raw_path = path or SETTINGS.database_path
        if raw_path == ":memory:":
            self.path = raw_path
        else:
            p = Path(raw_path)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                self.path = str(p)
            except PermissionError:
                fallback = Path("/tmp/smc_cloud.db")
                fallback.parent.mkdir(parents=True, exist_ok=True)
                self.path = str(fallback)
        self._lock = threading.RLock()
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._lock, self._conn() as c:
            c.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS snapshots(
                    id TEXT PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    session TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_generated_at ON snapshots(generated_at DESC);

                CREATE TABLE IF NOT EXISTS analyses(
                    id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    valid_until TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    ai_used INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analyses_generated_at ON analyses(generated_at DESC);

                CREATE TABLE IF NOT EXISTS feedback(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    signal_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS heartbeats(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plan_acks(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    analysis_id TEXT NOT NULL,
                    zone_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS news_events(
                    event_id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    title TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    released INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_news_ts ON news_events(ts ASC);

                CREATE TABLE IF NOT EXISTS audit_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nonces(
                    nonce TEXT PRIMARY KEY,
                    seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scheduler_runs(
                    run_key TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS replay_runs(
                    id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    label TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
            # Online migration for snapshot protocol v3. Existing Railway volumes
            # remain valid; old rows are treated as FULL_HISTORY/LEGACY.
            cols = {r[1] for r in c.execute("PRAGMA table_info(snapshots)").fetchall()}
            if "snapshot_kind" not in cols:
                c.execute("ALTER TABLE snapshots ADD COLUMN snapshot_kind TEXT NOT NULL DEFAULT 'FULL_HISTORY'")
            if "snapshot_reason" not in cols:
                c.execute("ALTER TABLE snapshots ADD COLUMN snapshot_reason TEXT NOT NULL DEFAULT 'LEGACY_OR_MANUAL'")
            c.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_kind_generated_at ON snapshots(snapshot_kind, generated_at DESC)")

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def audit(self, action: str, actor: str, details: str):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO audit_log(ts, action, actor, details) VALUES(?,?,?,?)",
                (self.now_iso(), action, actor, details[:4000]),
            )

    def save_snapshot(self, snapshot_id: str, generated_at: str, session: str, fingerprint: str, payload: dict):
        kind = str(payload.get("snapshot_kind") or "FULL_HISTORY").upper()
        reason = str(payload.get("snapshot_reason") or "LEGACY_OR_MANUAL")
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO snapshots
                   (id, generated_at, session, fingerprint, payload, created_at, snapshot_kind, snapshot_reason)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (snapshot_id, generated_at, session, fingerprint, json.dumps(payload), self.now_iso(), kind, reason),
            )
            # Railway volume protection: retain enough live snapshots for diagnostics
            # and enough heavy full syncs for audit, but do not grow forever.
            c.execute(
                """DELETE FROM snapshots WHERE id IN (
                     SELECT id FROM snapshots WHERE UPPER(snapshot_kind)='LIVE_UPDATE'
                     ORDER BY generated_at DESC LIMIT -1 OFFSET ?
                   )""",
                (max(1, SETTINGS.snapshot_live_retention),),
            )
            c.execute(
                """DELETE FROM snapshots WHERE id IN (
                     SELECT id FROM snapshots WHERE UPPER(snapshot_kind)='FULL_HISTORY'
                     ORDER BY generated_at DESC LIMIT -1 OFFSET ?
                   )""",
                (max(1, SETTINGS.snapshot_full_retention),),
            )

    def latest_snapshot(self) -> Optional[dict]:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM snapshots ORDER BY generated_at DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def latest_full_snapshot(self) -> Optional[dict]:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM snapshots WHERE UPPER(snapshot_kind)='FULL_HISTORY' ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def save_analysis(self, payload: dict):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO analyses(id, snapshot_id, generated_at, valid_until, approved, ai_used, payload, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    payload["analysis_id"], payload["snapshot_id"], payload["generated_at"], payload["valid_until"],
                    1 if payload.get("approved") else 0, 1 if payload.get("ai_used") else 0,
                    json.dumps(payload), self.now_iso(),
                ),
            )

    def latest_analysis(self, approved_only: bool = False) -> Optional[dict]:
        query = "SELECT * FROM analyses"
        if approved_only:
            query += " WHERE approved=1"
        query += " ORDER BY generated_at DESC LIMIT 1"
        with self._lock, self._conn() as c:
            row = c.execute(query).fetchone()
            return dict(row) if row else None

    def latest_execution_analysis(self, require_ai: bool = False) -> Optional[dict]:
        """Return the newest successfully validated plan eligible to remain active.

        When AI is mandatory, deterministic fallback/AI-failure analyses are kept
        for audit/dashboard visibility but do not replace the previous AI-validated
        execution plan. A later successful AI analysis, including an AI NO_TRADE
        decision, naturally supersedes the carried plan.
        """
        query = "SELECT * FROM analyses WHERE approved=1"
        params: list[Any] = []
        if require_ai:
            query += " AND ai_used=1"
        query += " ORDER BY generated_at DESC LIMIT 1"
        with self._lock, self._conn() as c:
            row = c.execute(query, params).fetchone()
            return dict(row) if row else None

    def add_feedback(self, payload: dict):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO feedback(ts, signal_id, event, payload) VALUES(?,?,?,?)",
                (payload["ts"], payload["signal_id"], payload["event"], json.dumps(payload)),
            )

    def add_heartbeat(self, payload: dict):
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO heartbeats(ts, payload) VALUES(?,?)", (payload["ts"], json.dumps(payload)))
            c.execute("DELETE FROM heartbeats WHERE id NOT IN (SELECT id FROM heartbeats ORDER BY id DESC LIMIT 1000)")

    def latest_heartbeat(self) -> Optional[dict]:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM heartbeats ORDER BY ts DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def add_ack(self, payload: dict):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO plan_acks(ts, analysis_id, zone_id, payload) VALUES(?,?,?,?)",
                (payload["ts"], payload["analysis_id"], payload["zone_id"], json.dumps(payload)),
            )

    def upsert_news(self, payload: dict):
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO news_events(event_id, ts, title, currency, impact, released, payload, updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(event_id) DO UPDATE SET ts=excluded.ts,title=excluded.title,currency=excluded.currency,
                   impact=excluded.impact,released=excluded.released,payload=excluded.payload,updated_at=excluded.updated_at""",
                (payload["event_id"], payload["ts"], payload["title"], payload["currency"], payload["impact"],
                 1 if payload.get("released") else 0, json.dumps(payload), self.now_iso()),
            )

    def list_news(self, limit: int = 50) -> list[dict]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM news_events ORDER BY ts ASC LIMIT ?", (limit,)).fetchall()]

    def nonce_seen(self, nonce: str) -> bool:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT 1 FROM nonces WHERE nonce=?", (nonce,)).fetchone()
            return bool(row)

    def remember_nonce(self, nonce: str, seen_at: str):
        with self._lock, self._conn() as c:
            c.execute("INSERT OR IGNORE INTO nonces(nonce, seen_at) VALUES(?,?)", (nonce, seen_at))

    def cleanup_nonces(self, cutoff_iso: str):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM nonces WHERE seen_at < ?", (cutoff_iso,))

    def scheduler_ran(self, run_key: str) -> bool:
        """Return True only after a successful scheduled analysis.

        Failed/skipped attempts remain auditable but do not permanently suppress retries
        inside the configured catch-up window.
        """
        with self._lock, self._conn() as c:
            row = c.execute("SELECT status FROM scheduler_runs WHERE run_key=?", (run_key,)).fetchone()
            return bool(row and str(row["status"]).lower() == "success")

    def list_scheduler_runs(self, limit: int = 20) -> list[dict]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM scheduler_runs ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()]

    def mark_scheduler_run(self, run_key: str, kind: str, status: str, details: str = ""):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO scheduler_runs(run_key, ts, kind, status, details) VALUES(?,?,?,?,?)",
                (run_key, self.now_iso(), kind, status, details[:4000]),
            )

    def add_replay(self, replay_id: str, label: str, payload: dict):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO replay_runs(id, ts, label, payload) VALUES(?,?,?,?)",
                (replay_id, self.now_iso(), label, json.dumps(payload)),
            )

    def dashboard_state(self) -> dict[str, Any]:
        snap = self.latest_snapshot()
        analysis = self.latest_analysis()
        hb = self.latest_heartbeat()
        news = self.list_news(20)
        return {
            "snapshot": json.loads(snap["payload"]) if snap else None,
            "analysis": json.loads(analysis["payload"]) if analysis else None,
            "heartbeat": json.loads(hb["payload"]) if hb else None,
            "news": [json.loads(x["payload"]) for x in news],
        }


DB = Database()
