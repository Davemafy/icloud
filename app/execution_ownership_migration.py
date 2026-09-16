from __future__ import annotations

import threading

from .db import connect

_SCHEMA_LOCK = threading.Lock()

_OWNERSHIP_COLUMNS = {
    "ownership_acquired_at": "INTEGER DEFAULT 0",
    "ownership_authority": "TEXT DEFAULT ''",
    "ownership_analysis_id": "TEXT DEFAULT ''",
    "ownership_anchor_price": "REAL DEFAULT 0",
}


def ensure_execution_ownership_schema() -> None:
    """Add explicit execution-ownership fields to the persisted zone lifecycle.

    This is an idempotent PAPER/DEMO migration. Existing lifecycle rows intentionally
    default to ownership_acquired_at=0, so a historical WATCH/INTERACTING observation
    cannot inherit an execution lock merely because it existed before this contract.
    A new lock must be acquired by an explicit execution handoff after deployment.
    """
    with _SCHEMA_LOCK, connect() as db:
        table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='zone_reactions'"
        ).fetchone()
        if table is None:
            return
        existing = {str(row["name"]) for row in db.execute("PRAGMA table_info(zone_reactions)").fetchall()}
        for name, declaration in _OWNERSHIP_COLUMNS.items():
            if name not in existing:
                db.execute(f"ALTER TABLE zone_reactions ADD COLUMN {name} {declaration}")
