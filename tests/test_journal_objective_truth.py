from types import SimpleNamespace

from app.main import _journal_target_progress
from app.models import Direction


def _zone():
    return SimpleNamespace(
        zone_id="SELL_OWNER",
        original_direction=Direction.SELL,
        original_target1=4351.33,
        original_target2=4341.13,
        original_target3=4320.18,
    )


def test_journal_target_progress_shows_only_still_open_owner_objectives():
    a = SimpleNamespace(
        execution_policy={
            "active_thesis": {
                "locked": True,
                "owner_zone_id": "SELL_OWNER",
                "direction": "SELL",
                "target1_hit_at": 100,
                "target2_hit_at": 200,
                "target3_hit_at": 0,
                "best_price": 4338.0,
            }
        }
    )
    result = _journal_target_progress(a, _zone())
    assert result["completed"] == [4351.33, 4341.13]
    assert result["remaining"] == [4320.18]
    assert result["next_open"] == 4320.18


def test_journal_target_progress_does_not_consume_unowned_map_targets():
    a = SimpleNamespace(execution_policy={"active_thesis": {"locked": False}})
    result = _journal_target_progress(a, _zone())
    assert result["remaining"] == [4351.33, 4341.13, 4320.18]
    assert result["next_open"] == 4351.33
