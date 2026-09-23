from __future__ import annotations

import threading

from .db import connect


_SCHEMA_LOCK = threading.Lock()

_PUBLICATION_COLUMNS = {
    "geometry_published_at": "INTEGER DEFAULT 0",
    "geometry_signature": "TEXT DEFAULT ''",
    "publication_qualified_mitigations": "INTEGER DEFAULT 0",
    "publication_raw_core_contacts": "INTEGER DEFAULT 0",
    "live_core_touched_at": "INTEGER DEFAULT 0",
    "live_core_touch_basis": "TEXT DEFAULT ''",
    "live_core_touch_price": "REAL DEFAULT 0",
}


def ensure_zone_publication_schema() -> None:
    """Add fail-safe publication-time execution-truth fields.

    Existing historical core_touched_at values are not trusted for new execution
    authority. Only rows that already acquired explicit HTF_CORE_HANDOFF ownership
    are backfilled into live_core_touched_at; all other legacy rows must earn a new
    post-publication live contact.
    """
    with _SCHEMA_LOCK, connect() as db:
        table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='zone_reactions'"
        ).fetchone()
        if table is None:
            return

        existing = {
            str(row["name"])
            for row in db.execute("PRAGMA table_info(zone_reactions)").fetchall()
        }
        for name, declaration in _PUBLICATION_COLUMNS.items():
            if name not in existing:
                db.execute(f"ALTER TABLE zone_reactions ADD COLUMN {name} {declaration}")

        db.execute(
            """
            UPDATE zone_reactions
            SET live_core_touched_at=core_touched_at,
                live_core_touch_basis='LEGACY_EXPLICIT_HTF_CORE_OWNER',
                live_core_touch_price=CASE
                    WHEN direction='SELL' THEN core_low
                    ELSE core_high
                END
            WHERE COALESCE(live_core_touched_at,0)=0
              AND COALESCE(core_touched_at,0)>0
              AND COALESCE(ownership_acquired_at,0)>0
              AND ownership_authority='HTF_CORE_HANDOFF'
            """
        )
