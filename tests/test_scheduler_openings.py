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


def _drift_settings(**overrides):
    base = dict(
        paper_only=True,
        market_drift_reanalysis_h1_atr=2.0,
        market_drift_reanalysis_step_h1_atr=0.5,
        market_drift_reanalysis_min_age_minutes=10,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _drift_analysis(*, generated_at=1_000, readiness="ARMED", direction="SELL"):
    zone = SimpleNamespace(
        zone_id="PZ_REMOTE",
        original_direction=SimpleNamespace(value=direction),
        zone_low=4_306.0 if direction == "SELL" else 4_000.0,
        zone_high=4_317.0 if direction == "SELL" else 4_010.0,
        core_method=f"{readiness}|MASTER_SNIPER_SOURCE_EXACT",
    )
    return SimpleNamespace(
        generated_at=generated_at,
        selected_zone_id=zone.zone_id,
        zones=[zone],
    )


def _drift_snap(mid=4_215.0, sent_at=7_300, closed_h1_ts=3_600):
    bar = SimpleNamespace(ts=closed_h1_ts)
    return SimpleNamespace(mid=mid, atr_h1=40.0, xau_h1=[bar], sent_at=sent_at)


def test_market_drift_requests_early_reanalysis_for_remote_unowned_armed_map(monkeypatch):
    monkeypatch.setattr(scheduler, "SETTINGS", _drift_settings())
    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: _drift_analysis())
    monkeypatch.setattr(scheduler, "active_owner_snapshot", lambda now: None)

    snap = _drift_snap()
    out = scheduler._market_drift_refresh(snap, now_utc=7_300)

    assert out["zone_id"] == "PZ_REMOTE"
    assert out["direction"] == "SELL"
    assert out["distance_h1_atr"] > 2.0
    assert out["signature"] == "PZ_REMOTE|SELL|H1:3600"
    assert out["cadence"] == "NEW_CLOSED_H1_ONLY"


def test_market_drift_does_not_reanalyse_too_soon(monkeypatch):
    monkeypatch.setattr(scheduler, "SETTINGS", _drift_settings())
    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: _drift_analysis(generated_at=1_500))
    monkeypatch.setattr(scheduler, "active_owner_snapshot", lambda now: None)

    snap = _drift_snap()
    assert scheduler._market_drift_refresh(snap, now_utc=1_900) == {}


def test_market_drift_never_overrides_active_thesis_owner(monkeypatch):
    monkeypatch.setattr(scheduler, "SETTINGS", _drift_settings())
    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: _drift_analysis())
    monkeypatch.setattr(scheduler, "active_owner_snapshot", lambda now: {"reaction_key": "OWNER"})

    snap = _drift_snap()
    assert scheduler._market_drift_refresh(snap, now_utc=7_300) == {}


def test_market_drift_requires_uncontacted_map_state(monkeypatch):
    monkeypatch.setattr(scheduler, "SETTINGS", _drift_settings())
    monkeypatch.setattr(
        scheduler,
        "latest_analysis",
        lambda ai_required=False: _drift_analysis(readiness="INTERACTING"),
    )
    monkeypatch.setattr(scheduler, "active_owner_snapshot", lambda now: None)

    snap = _drift_snap()
    assert scheduler._market_drift_refresh(snap, now_utc=7_300) == {}


def test_market_drift_signature_waits_for_new_closed_h1_not_more_ticks(monkeypatch):
    monkeypatch.setattr(scheduler, "SETTINGS", _drift_settings())
    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: _drift_analysis())
    monkeypatch.setattr(scheduler, "active_owner_snapshot", lambda now: None)

    near = _drift_snap(mid=4_215.0, sent_at=7_300, closed_h1_ts=3_600)
    farther_same_h1 = _drift_snap(mid=4_190.0, sent_at=7_500, closed_h1_ts=3_600)
    next_h1 = _drift_snap(mid=4_190.0, sent_at=10_900, closed_h1_ts=7_200)

    a = scheduler._market_drift_refresh(near, now_utc=7_300)
    b = scheduler._market_drift_refresh(farther_same_h1, now_utc=7_500)
    c = scheduler._market_drift_refresh(next_h1, now_utc=10_900)

    assert a["signature"] == b["signature"]
    assert c["signature"] != a["signature"]


def test_market_drift_requires_a_causally_closed_h1_bar(monkeypatch):
    monkeypatch.setattr(scheduler, "SETTINGS", _drift_settings())
    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: _drift_analysis())
    monkeypatch.setattr(scheduler, "active_owner_snapshot", lambda now: None)

    forming = SimpleNamespace(mid=4_215.0, atr_h1=40.0, xau_h1=[SimpleNamespace(ts=7_200)], sent_at=7_300)
    assert scheduler._market_drift_refresh(forming, now_utc=7_300) == {}


def test_market_drift_does_not_replace_wrong_side_lifecycle_logic(monkeypatch):
    monkeypatch.setattr(scheduler, "SETTINGS", _drift_settings())
    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: _drift_analysis())
    monkeypatch.setattr(scheduler, "active_owner_snapshot", lambda now: None)

    # SELL map is no longer above price; that belongs to invalidation/flip logic.
    snap = _drift_snap(mid=4_320.0)
    assert scheduler._market_drift_refresh(snap, now_utc=7_300) == {}


def test_interaction_ids_distinguish_approach_from_exact_core_contact(monkeypatch):
    settings = SimpleNamespace(paper_only=True)
    monkeypatch.setattr(scheduler, "SETTINGS", settings)

    zone = SimpleNamespace(zone_id="PZ_TEST")
    analysis = SimpleNamespace(zones=[zone])
    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: analysis)
    monkeypatch.setattr(scheduler, "owner_core_interacting", lambda snap: None)
    monkeypatch.setattr(scheduler, "publication_state_for_zone", lambda z: {})

    monkeypatch.setattr(
        scheduler,
        "primary_zone_interacting",
        lambda z, snap: bool(getattr(snap, "core", False)),
    )
    monkeypatch.setattr(
        scheduler,
        "primary_zone_approaching",
        lambda z, snap: bool(getattr(snap, "approach", False)),
    )

    approach = SimpleNamespace(approach=True, core=False)
    contact = SimpleNamespace(approach=True, core=True)

    assert scheduler._interaction_ids(approach) == {"APPROACH:PZ_TEST"}
    assert scheduler._interaction_ids(contact) == {"CORE:PZ_TEST"}


def test_interaction_ids_recover_persisted_contact_even_after_quote_leaves_core(monkeypatch):
    settings = SimpleNamespace(paper_only=True)
    monkeypatch.setattr(scheduler, "SETTINGS", settings)

    zone = SimpleNamespace(zone_id="PZ_TEST")
    analysis = SimpleNamespace(zones=[zone])
    monkeypatch.setattr(scheduler, "latest_analysis", lambda ai_required=False: analysis)
    monkeypatch.setattr(scheduler, "owner_core_interacting", lambda snap: None)
    monkeypatch.setattr(scheduler, "primary_zone_interacting", lambda z, snap: False)
    monkeypatch.setattr(scheduler, "primary_zone_approaching", lambda z, snap: False)
    monkeypatch.setattr(
        scheduler,
        "publication_state_for_zone",
        lambda z: {"live_core_touched_at": 123456},
    )

    assert scheduler._interaction_ids(SimpleNamespace()) == {
        "CONTACT:PZ_TEST:123456"
    }
