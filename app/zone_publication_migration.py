from __future__ import annotations

import threading

from .db import connect


_SCHEMA_LOCK = threading.Lock()


def ensure_zone_publication_schema() -> None:
    """Create exact-geometry publication truth for fail-safe execution handoff.

    A source-level lifecycle row can survive re-selection and geometry changes. That
    is useful for research, but execution must know when the *current geometry* was
    actually published. Each exact geometry therefore gets its own publication row.
    Historical source contacts before that timestamp can never create M1 authority.
    """
    with _SCHEMA_LOCK, connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS zone_publications(
                publication_key TEXT PRIMARY KEY,
                reaction_key TEXT NOT NULL,
                geometry_signature TEXT NOT NULL,
                first_analysis_id TEXT,
                latest_analysis_id TEXT,
                zone_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                source_tf TEXT,
                source_ts INTEGER DEFAULT 0,
                core_low REAL NOT NULL,
                core_high REAL NOT NULL,
                zone_low REAL NOT NULL,
                zone_high REAL NOT NULL,
                first_published_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                publication_qualified_mitigations INTEGER DEFAULT 0,
                publication_raw_core_contacts INTEGER DEFAULT 0,
                live_core_touched_at INTEGER DEFAULT 0,
                live_core_touch_basis TEXT DEFAULT '',
                live_core_touch_price REAL DEFAULT 0,
                live_core_touch_analysis_id TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'PUBLISHED'
            );
            CREATE INDEX IF NOT EXISTS idx_zone_publications_reaction
                ON zone_publications(reaction_key,last_seen_at);
            CREATE INDEX IF NOT EXISTS idx_zone_publications_analysis
                ON zone_publications(latest_analysis_id,last_seen_at);
            CREATE INDEX IF NOT EXISTS idx_zone_publications_zone
                ON zone_publications(zone_id,last_seen_at);
            """
        )
