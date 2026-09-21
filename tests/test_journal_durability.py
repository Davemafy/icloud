from types import SimpleNamespace

from app import db
from app.models import Feedback


def test_feedback_event_uid_falls_back_to_stable_deal_and_position_keys():
    entry = Feedback(ts=1, event="ENTRY_OPENED", details={"deal_id": 123, "position_id": 77})
    closed = Feedback(ts=2, event="TRADE_CLOSED", details={"position_id": 77})
    explicit = Feedback(ts=3, event="TP_HIT", details={"event_uid": "EXPLICIT"})

    assert db._feedback_event_uid(entry) == "ENTRY_OPENED|DEAL|123"
    assert db._feedback_event_uid(closed) == "TRADE_CLOSED|POSITION|77"
    assert db._feedback_event_uid(explicit) == "EXPLICIT"


def test_save_feedback_is_idempotent_for_replayed_mt5_history(tmp_path, monkeypatch):
    settings = SimpleNamespace(db_path=str(tmp_path / "journal.db"), ml_data_enabled=False)
    monkeypatch.setattr(db, "SETTINGS", settings)
    db.init_db()

    event = Feedback(
        ts=10,
        event="TP_HIT",
        analysis_id="MT5_HISTORY",
        zone_id="",
        price=95.0,
        details={
            "event_uid": "TP_HIT|DEAL|9002",
            "position_id": 777,
            "deal_id": 9002,
            "net_profit": 25.0,
        },
    )
    db.save_feedback(event)
    db.save_feedback(event)

    with db.connect() as conn:
        feedback_count = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        key_count = conn.execute("SELECT COUNT(*) FROM feedback_event_keys").fetchone()[0]

    assert feedback_count == 1
    assert key_count == 1
