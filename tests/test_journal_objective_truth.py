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
    assert result["scope"] == "ACTIVE_THESIS"


def test_journal_target_progress_does_not_consume_unowned_map_targets():
    a = SimpleNamespace(execution_policy={"active_thesis": {"locked": False}})
    result = _journal_target_progress(a, _zone())
    assert result["remaining"] == [4351.33, 4341.13, 4320.18]
    assert result["next_open"] is None
    assert result["completed"] == []
    assert result["scope"] == "PLAN"


def test_prezone_handoff_does_not_label_targets_behind_anchor_as_completed_thesis_targets():
    a = SimpleNamespace(
        execution_policy={
            "active_thesis": {
                "locked": True,
                "owner_zone_id": "SELL_OWNER",
                "direction": "SELL",
                "ownership_authority": "LIQUIDITY_REVERSAL_HANDOFF",
                "ownership_anchor_price": 4340.0,
                "target1_hit_at": 100,
                "target2_hit_at": 200,
                "target3_hit_at": 0,
                "best_price": 4338.0,
            }
        }
    )
    z = _zone()
    z.zone_low = 4368.61
    z.zone_high = 4394.61

    result = _journal_target_progress(a, z)

    assert result["scope"] == "PREZONE_HANDOFF"
    assert result["completed"] == []
    assert result["remaining"] == [4320.18]
    assert result["next_open"] == 4320.18
