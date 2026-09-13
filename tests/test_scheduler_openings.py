from datetime import datetime
from types import SimpleNamespace

import app.scheduler as scheduler


def test_week_open_and_daily_open_reasons_are_distinct(monkeypatch):
    settings=SimpleNamespace(
        session_analysis_times="07:50,12:50,15:20",
        trading_day_open_time="23:06",
        trading_day_weekdays="0,1,2,3",
        week_open_weekday=6,
        week_open_time="23:11",
        timezone_name="Africa/Lagos",
        scheduler_poll_seconds=20,
    )
    monkeypatch.setattr(scheduler,"SETTINGS",settings)
    monkeypatch.setattr(scheduler,"latest_snapshot",lambda: None)
    sunday=datetime(2026,9,13,23,11)
    monday=datetime(2026,9,14,23,6)
    assert "WEEK_OPEN" in scheduler._due_reasons(sunday)
    assert "TRADING_DAY_OPEN" not in scheduler._due_reasons(sunday)
    assert "TRADING_DAY_OPEN" in scheduler._due_reasons(monday)


def test_existing_session_times_are_preserved(monkeypatch):
    settings=SimpleNamespace(
        session_analysis_times="07:50,12:50,15:20",
        trading_day_open_time="23:06",
        trading_day_weekdays="0,1,2,3",
        week_open_weekday=6,
        week_open_time="23:11",
        timezone_name="Africa/Lagos",
        scheduler_poll_seconds=20,
    )
    monkeypatch.setattr(scheduler,"SETTINGS",settings)
    monkeypatch.setattr(scheduler,"latest_snapshot",lambda: None)
    t=datetime(2026,9,14,7,50)
    assert "SESSION_0750" in scheduler._due_reasons(t)
