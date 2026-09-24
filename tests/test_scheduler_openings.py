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


def test_startup_bootstrap_requires_fresh_complete_snapshot(monkeypatch):
    settings=SimpleNamespace(max_snapshot_age_seconds=120)
    monkeypatch.setattr(scheduler,"SETTINGS",settings)
    fresh=SimpleNamespace(sent_at=1000,complete=lambda: True)
    stale=SimpleNamespace(sent_at=800,complete=lambda: True)
    incomplete=SimpleNamespace(sent_at=1000,complete=lambda: False)
    assert scheduler._fresh_complete_snapshot(fresh,1100) is True
    assert scheduler._fresh_complete_snapshot(stale,1100) is False
    assert scheduler._fresh_complete_snapshot(incomplete,1100) is False


def test_wrong_side_context_triggers_requalification_but_selected_zone_is_preserved(monkeypatch):
    settings = SimpleNamespace(paper_only=True)
    monkeypatch.setattr(scheduler, "SETTINGS", settings)

    sell = SimpleNamespace(
        zone_id="PZ_H1_SELL_16",
        original_direction=SimpleNamespace(value="SELL"),
        zone_low=4302.19,
        zone_high=4324.19,
    )
    buy = SimpleNamespace(
        zone_id="PZ_H1_BUY_7",
        original_direction=SimpleNamespace(value="BUY"),
        zone_low=4256.34,
        zone_high=4272.20,
    )
    analysis = SimpleNamespace(
        selected_zone_id="PZ_H1_SELL_16",
        zones=[sell, buy],
    )
    snap = SimpleNamespace(sent_at=1_000, mid=4255.33)

    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: analysis)
    monkeypatch.setattr(scheduler, "active_owner_snapshot", lambda now: None)

    assert scheduler._wrong_side_context_ids(snap) == {"PZ_H1_BUY_7"}

    # A selected plan is deliberately not discarded by this scheduler helper;
    # selected/owned geometry may still be needed for accepted-invalidation/flip monitoring.
    analysis.selected_zone_id = "PZ_H1_BUY_7"
    assert scheduler._wrong_side_context_ids(snap) == set()
