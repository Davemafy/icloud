from pathlib import Path

from app import db


def test_replay_fast_db_reuses_one_connection_and_uses_disposable_pragmas(tmp_path, monkeypatch):
    old_path = db.SETTINGS.db_path
    try:
        db.SETTINGS.db_path = str(tmp_path / "replay.db")
        monkeypatch.setenv("TRADEZONE_REPLAY_FAST_DB", "1")
        if getattr(db._replay_local, "connection", None) is not None:
            try:
                db._replay_local.connection.close()
            except Exception:
                pass
            db._replay_local.connection = None
            db._replay_local.path = ""

        first = db.connect()
        second = db.connect()
        assert first is second
        assert first.execute("PRAGMA journal_mode").fetchone()[0].lower() == "memory"
        assert first.execute("PRAGMA synchronous").fetchone()[0] == 0
        assert first.execute("PRAGMA temp_store").fetchone()[0] == 2
    finally:
        conn = getattr(db._replay_local, "connection", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        db._replay_local.connection = None
        db._replay_local.path = ""
        db.SETTINGS.db_path = old_path


def test_live_db_connect_path_remains_wal_and_not_reused(tmp_path, monkeypatch):
    old_path = db.SETTINGS.db_path
    try:
        db.SETTINGS.db_path = str(tmp_path / "live.db")
        monkeypatch.delenv("TRADEZONE_REPLAY_FAST_DB", raising=False)
        first = db.connect()
        second = db.connect()
        assert first is not second
        assert first.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        first.close()
        second.close()
    finally:
        db.SETTINGS.db_path = old_path


def test_backtest_child_explicitly_enables_fast_replay_db():
    text = Path("app/backtest.py").read_text(encoding="utf-8")
    assert 'env["TRADEZONE_REPLAY_FAST_DB"] = "1"' in text
