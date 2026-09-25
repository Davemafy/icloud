from __future__ import annotations

import threading

from .db import connect, _path

_SCHEMA_LOCK = threading.Lock()
_READY_PATHS: set[str] = set()

_OWNERSHIP_COLUMNS = {
    "ownership_acquired_at": "INTEGER DEFAULT 0",
    "ownership_authority": "TEXT DEFAULT ''",
    "ownership_analysis_id": "TEXT DEFAULT ''",
    "ownership_anchor_price": "REAL DEFAULT 0",
    "ownership_zone_id": "TEXT DEFAULT ''",
    "ownership_zone_payload": "TEXT DEFAULT ''",
}


def ensure_execution_ownership_schema() -> None:
    """Add explicit execution-ownership fields to the persisted zone lifecycle.

    The migration is cached per physical database path after its first successful
    verification. This keeps live semantics unchanged while avoiding thousands of
    redundant sqlite_master/PRAGMA checks during historical replay.
    """
    key = str(_path())
    if key in _READY_PATHS:
        return
    with _SCHEMA_LOCK:
        if key in _READY_PATHS:
            return
        with connect() as db:
            table = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='zone_reactions'"
            ).fetchone()
            if table is None:
                return
            existing = {str(row["name"]) for row in db.execute("PRAGMA table_info(zone_reactions)").fetchall()}
            for name, declaration in _OWNERSHIP_COLUMNS.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE zone_reactions ADD COLUMN {name} {declaration}")
        _READY_PATHS.add(key)
