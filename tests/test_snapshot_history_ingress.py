import pytest
from fastapi import HTTPException

from app import main
from app.models import MarketSnapshot


def _snapshot():
    return MarketSnapshot(
        sent_at=1000,
        bid=4260.0,
        ask=4260.18,
        spread_points=18.0,
        point=0.01,
    )


def test_incomplete_history_snapshot_is_not_saved(monkeypatch):
    saved = []
    monkeypatch.setattr(main, "history_audit", lambda _s: (False, ["XAU_D1_1Y"]))
    monkeypatch.setattr(main, "history_metrics", lambda _s: {"XAU_D1_bars": 280, "XAU_D1_span_days": 326.0})
    monkeypatch.setattr(main, "save_snapshot", lambda s: saved.append(s))

    with pytest.raises(HTTPException) as exc:
        main.market_snapshot(_snapshot())

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "MASTER_SNIPER_HISTORY_WINDOW_INCOMPLETE"
    assert exc.value.detail["failures"] == ["XAU_D1_1Y"]
    assert saved == []


def test_complete_history_snapshot_is_saved(monkeypatch):
    saved = []
    monkeypatch.setattr(main, "history_audit", lambda _s: (True, []))
    monkeypatch.setattr(main, "history_metrics", lambda _s: {"XAU_D1_bars": 390, "XAU_D1_span_days": 390.0})
    monkeypatch.setattr(main, "save_snapshot", lambda s: saved.append(s))

    result = main.market_snapshot(_snapshot())

    assert result["ok"] is True
    assert result["history_window_ok"] is True
    assert result["history_window_failures"] == []
    assert len(saved) == 1


def test_health_uses_professional_history_audit(monkeypatch):
    snapshot = _snapshot()
    monkeypatch.setattr(main, "latest_snapshot", lambda: snapshot)
    monkeypatch.setattr(main, "active_analysis", lambda: None)
    monkeypatch.setattr(main, "system_status", lambda: {"components": {}})
    monkeypatch.setattr(main, "scheduler_status", lambda: {})
    monkeypatch.setattr(main, "history_audit", lambda _s: (False, ["XAU_H4_4M"]))

    payload = main.health()

    assert payload["snapshot_ready"] is False
    assert payload["snapshot_history_failures"] == ["XAU_H4_4M"]
