from __future__ import annotations

import os
import threading

from . import db as db_module

_SCHEMA_LOCK = threading.Lock()
_READY_DATABASES: set[tuple[str, int, int]] = set()


def _database_identity() -> tuple[str, int, int]:
    path = str(db_module._path())
    try:
        stat = os.stat(path)
        return (path, int(stat.st_ino), int(stat.st_ctime_ns))
    except OSError:
        return (path, 0, 0)


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

    Successful verification is cached by the physical SQLite file identity. If a
    test or replay replaces the DB at the same pathname, inode/ctime changes and
    the migration is verified again.
    """
    identity = _database_identity()
    if identity in _READY_DATABASES:
        return
    with _SCHEMA_LOCK:
        identity = _database_identity()
        if identity in _READY_DATABASES:
            return
        with db_module.connect() as db:
            table = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='zone_reactions'"
            ).fetchone()
            if table is None:
                return
            existing = {str(row["name"]) for row in db.execute("PRAGMA table_info(zone_reactions)").fetchall()}
            for name, declaration in _OWNERSHIP_COLUMNS.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE zone_reactions ADD COLUMN {name} {declaration}")
        _READY_DATABASES.add(_database_identity())
