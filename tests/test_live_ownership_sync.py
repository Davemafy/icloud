from types import SimpleNamespace

from app.live_ownership_sync import (
    _append_guard_reason,
    _dashboard_wording,
    _plan_block_reason,
    _zone_render_sync,
    sync_analysis_live_ownership,
)
from app import thesis_ownership_policy
from app.models import Analysis, Direction, Grade, Zone, ZoneState


def test_release_of_previously_locked_owner_fails_closed_until_reanalysis(monkeypatch):
    monkeypatch.setattr(thesis_ownership_policy, "active_owner_snapshot", lambda now: None)
    a = SimpleNamespace(
        zones=[],
        selected_zone_id="SELL_1",
        execution_policy={"active_thesis": {"locked": True, "owner_zone_id": "SELL_1"}},
    )
    sync_analysis_live_ownership(a, 1000)
    assert a.execution_policy["active_thesis"]["locked"] is False
    assert a.execution_policy["live_thesis_sync"]["release_pending_reanalysis"] is True
    assert _plan_block_reason(a) == "LIVE_THESIS_RELEASE_REANALYSIS_REQUIRED"


def test_live_owner_refreshes_target_progress_and_owner_mapping(monkeypatch):
    owner = {
        "reaction_key": "SELL|H4>H1|123",
        "latest_zone_id": "SELL_1",
        "direction": "SELL",
        "source_tf": "H4>H1",
        "source_ts": 123,
        "status": "OBJECTIVE_IN_PROGRESS",
        "ownership_acquired_at": 900,
        "ownership_authority": "HTF_CORE_HANDOFF",
        "ownership_analysis_id": "A1",
        "ownership_anchor_price": 4360.0,
        "target1": 4341.13,
        "target2": 4324.68,
        "target3": 4299.37,
        "target1_hit_at": 950,
        "target2_hit_at": 980,
        "target3_hit_at": 0,
        "best_price": 4315.0,
        "mfe_price": 45.0,
        "last_reason": "LIQUIDITY_OBJECTIVE_PROGRESS",
    }
    monkeypatch.setattr(thesis_ownership_policy, "active_owner_snapshot", lambda now: owner)
    z = SimpleNamespace(
        zone_id="SELL_1",
        original_direction=SimpleNamespace(value="SELL"),
        source_tf="H4>H1",
        source_ts=123,
    )
    a = SimpleNamespace(zones=[z], selected_zone_id="SELL_1", execution_policy={})
    sync_analysis_live_ownership(a, 1000)
    meta = a.execution_policy["active_thesis"]
    assert meta["locked"] is True
    assert meta["owner_zone_id"] == "SELL_1"
    assert meta["status"] == "OBJECTIVE_IN_PROGRESS"
    assert meta["best_price"] == 4315.0
    assert meta["target1_hit_at"] == 950
    assert meta["target2_hit_at"] == 980
    assert _plan_block_reason(a) == ""


def test_plan_guard_forces_watch_only_without_erasing_existing_reason():
    raw = (
        "protocol=6\n"
        "ea_mode=DUAL_BRANCH\n"
        "execution_authority=HTF_CORE_HANDOFF\n"
        "core_handoff_ready=1\n"
        "liquidity_handoff_ready=0\n"
        "execution_guard_reason=\n"
    )
    out = _append_guard_reason(raw, "LIVE_THESIS_RELEASE_REANALYSIS_REQUIRED")
    assert "ea_mode=WATCH_ONLY\n" in out
    assert "execution_authority=NONE\n" in out
    assert "core_handoff_ready=0\n" in out
    assert "execution_guard_reason=LIVE_THESIS_RELEASE_REANALYSIS_REQUIRED\n" in out


def test_unlocked_chart_selection_is_not_marked_as_execution_authority():
    raw = (
        "protocol=2\n"
        "active_thesis_locked=0\n"
        "zone1_execution_authority=1\n"
        "zone2_execution_authority=0\n"
    )
    out = _zone_render_sync(raw)
    assert "zone1_execution_authority=0\n" in out
    assert "zone2_execution_authority=0\n" in out


def test_dashboard_selected_unlocked_wording_is_beginner_safe():
    raw = "SELECTED • UNLOCKED | SELECTED / UNLOCKED | is the current execution selection, subject to all normal M1 and safety gates."
    out = _dashboard_wording(raw)
    assert "PLAN SELECTED • NO EXECUTION AUTHORITY" in out
    assert "PLAN SELECTED / NO EXECUTION AUTHORITY" in out
    assert "current plan selection only" in out



def test_live_sync_injects_exact_frozen_owner_when_current_map_reranks(monkeypatch):
    frozen = Zone(
        zone_id="SELL_OWNER",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=4392.19,
        core_high=4398.19,
        core_method="M1_READY|THESIS_CONTINUATION|PROMPT",
        location_score=9.0,
        zone_low=4386.86,
        zone_high=4407.49,
        touch_count=1,
        independent_confluence_count=6,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "BSL_IN_MARKED_ZONE"],
        source_ts=123,
        invalidation_level=4407.49,
        invalidation_rule="M15 accepted invalidation",
        original_target1=4351.33,
        original_target2=4341.13,
        clear_run=40.86,
    )
    reranked = frozen.model_copy(
        update={
            "zone_id": "SELL_NEW",
            "core_low": 4429.05,
            "core_high": 4435.05,
            "zone_low": 4414.05,
            "zone_high": 4440.05,
            "source_ts": 999,
        }
    )
    owner = {
        "reaction_key": "SELL|H4>H1|123",
        "latest_zone_id": "SELL_NEW",
        "ownership_zone_id": "SELL_OWNER",
        "ownership_zone_payload": frozen.model_dump_json(),
        "direction": "SELL",
        "source_tf": "H4>H1",
        "source_ts": 123,
        "status": "OBJECTIVE_IN_PROGRESS",
        "ownership_acquired_at": 900,
        "ownership_authority": "HTF_CORE_HANDOFF",
        "ownership_analysis_id": "A_OWNER",
        "ownership_anchor_price": 4395.0,
        "target1": 4351.33,
        "target2": 4341.13,
        "target3": 4319.88,
        "target1_hit_at": 950,
        "target2_hit_at": 0,
        "target3_hit_at": 0,
        "best_price": 4348.0,
        "objective_complete_at": 0,
        "invalidated_at": 0,
    }
    monkeypatch.setattr(thesis_ownership_policy, "active_owner_snapshot", lambda now: owner)
    analysis = Analysis(
        analysis_id="A_NEW",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[reranked],
        selected_zone_id="SELL_NEW",
    )

    synced = sync_analysis_live_ownership(analysis, 1000)
    assert synced.selected_zone_id == "SELL_OWNER"
    assert synced.zones[0].zone_id == "SELL_OWNER"
    assert synced.zones[0].core_low == 4392.19
    assert synced.execution_policy["active_thesis"]["owner_zone_id"] == "SELL_OWNER"
    assert _plan_block_reason(synced) == ""
