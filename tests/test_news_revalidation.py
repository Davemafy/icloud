from datetime import datetime, timedelta, timezone

from app.db import DB
from app.news import blackout_state


def test_news_blackout_is_t_minus_10_through_but_not_including_t_plus_10():
    event_ts = datetime(2099, 10, 1, 12, 30, tzinfo=timezone.utc)
    DB.upsert_news({
        "event_id": "test-blackout-boundary-001",
        "ts": event_ts.isoformat(),
        "currency": "USD",
        "impact": "HIGH",
        "title": "Boundary Test Event",
        "released": False,
        "actual": None,
        "forecast": "1",
        "previous": "1",
        "source": "test",
    })
    active, _, _ = blackout_state(event_ts - timedelta(minutes=10))
    assert active is True
    active, _, _ = blackout_state(event_ts + timedelta(minutes=9, seconds=59))
    assert active is True
    active, _, _ = blackout_state(event_ts + timedelta(minutes=10))
    assert active is False
