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
    # One-way lifecycle tightening only: when a newly qualified active opposing
    # primary appears in front of an already-acquired thesis, the frozen owner
    # targets remain audit truth while this cap becomes the effective destination.
    "ownership_objective_cap": "REAL DEFAULT 0",
    "ownership_objective_cap_zone_id": "TEXT DEFAULT ''",
    "ownership_objective_cap_set_at": "INTEGER DEFAULT 0",
    "ownership_objective_cap_reached_at": "INTEGER DEFAULT 0",
    "ownership_objective_cap_reason": "TEXT DEFAULT ''",
    # Execution-lock release is distinct from lifecycle completion. A terminal
    # P0/R1/R2 campaign may be flat with its final objective still open; in that
    # case the thesis remains audit truth but must no longer monopolize new execution.
    "ownership_execution_released_at": "INTEGER DEFAULT 0",
    "ownership_execution_release_reason": "TEXT DEFAULT ''",
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
