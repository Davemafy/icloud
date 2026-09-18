from app import db
from app.models import Analysis, Bar, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.service import _stamp_execution_authority
from app.thesis_ownership_policy import acquire_execution_ownership, apply_thesis_ownership
from app.watch_ready import promote_watch_to_m1_ready, watch_zone_ready
from app.zone_reaction_lifecycle import register_analysis_zones


def _snapshot(mid: float = 98.0, ts: int = 1200, reclaimed: bool = True) -> MarketSnapshot:
    close = 101.50 if reclaimed else 102.30
    return MarketSnapshot(
        sent_at=ts,
        bid=mid - 0.08,
        ask=mid + 0.08,
        spread_points=16.0,
        point=0.01,
        atr_h1=10.0,
        atr_m15=2.0,
        xau_m15=[
            Bar(ts=1080, open=99.0, high=100.0, low=98.5, close=99.5),
            Bar(ts=1140, open=100.5, high=102.50, low=99.8, close=close),
        ],
    )


def _sell(zone_id: str = "SELL_OWNER", core_low: float = 104.0, core_high: float = 105.0) -> Zone:
    return Zone(
        zone_id=zone_id,
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=core_low,
        core_high=core_high,
        core_method="ARMED|TEST",
        location_score=8.0,
        zone_low=95.0,
        zone_high=105.0,
        touch_count=0,
        independent_confluence_count=5,
        confluences=[
            "LIQUIDITY_IN_MARKED_ZONE",
            "BSL_IN_MARKED_ZONE",
            "INSTITUTIONAL_DISPLACEMENT",
        ],
        source_ts=777,
        invalidation_level=105.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=90.0,
        original_target2=85.0,
        clear_run=14.0,
        notes=["attached_liquidity:BSL:H1_BSL@102.00000"],
    )


def test_outer_zone_liquidity_sweep_can_grant_m1_search_without_core(tmp_path, monkeypatch):
    path = tmp_path / "sweep_handoff.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    zone = _sell()
    analysis = Analysis(
        analysis_id="A_SWEEP",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )
    register_analysis_zones(analysis)
    snap = _snapshot()

    # Mid 98 is far below the 104-105 core; authority is earned by the BSL raid/reclaim.
    assert watch_zone_ready(zone, snap) is True
    ready = promote_watch_to_m1_ready(analysis, snap)
    assert ready is zone
    window = analysis.execution_policy["execution_window"]
    assert window["mode"] == "LATCHED_AFTER_ZONE_SWEEP"
    assert window["sweep_confirmed"] is True
    assert window["core_now"] is False
    assert window["core_required_for_authority"] is False
    assert _stamp_execution_authority(analysis, ready, {}) == "HTF_ZONE_SWEEP_HANDOFF"


def test_touch_without_sweep_reclaim_does_not_grant_authority(tmp_path, monkeypatch):
    path = tmp_path / "no_sweep_handoff.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    zone = _sell()
    analysis = Analysis(
        analysis_id="A_NO_SWEEP",
        generated_at=1000,
        snapshot_at=1000,
        zones=[zone],
        selected_zone_id=zone.zone_id,
    )
    register_analysis_zones(analysis)
    assert watch_zone_ready(zone, _snapshot(reclaimed=False)) is False


def test_acquired_owner_keeps_original_id_and_geometry_after_rerank(tmp_path, monkeypatch):
    path = tmp_path / "owner_freeze.db"
    monkeypatch.setattr(db, "_path", lambda: str(path))
    db.init_db()

    snap = _snapshot()
    original = _sell("SELL_ORIGINAL", 104.0, 105.0)
    first = Analysis(
        analysis_id="A_OWNER",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[original],
        selected_zone_id=original.zone_id,
        approved=True,
        ai_approved=True,
    )
    register_analysis_zones(first)

    acquired = acquire_execution_ownership(
        first, snap, "HTF_ZONE_SWEEP_HANDOFF", original.zone_id, anchor_price=102.0
    )
    assert acquired is not None
    assert acquired["ownership_zone_id"] == "SELL_ORIGINAL"
    assert acquired["ownership_zone_payload"]

    # A later analysis republishes the same source under a different id/geometry.
    reranked = _sell("SELL_RERANKED", 110.0, 111.0)
    reranked.zone_low = 108.0
    reranked.zone_high = 112.0
    second = Analysis(
        analysis_id="A_NEXT",
        generated_at=1201,
        snapshot_at=1201,
        overall_bias=Direction.SELL,
        zones=[reranked],
        selected_zone_id=reranked.zone_id,
    )

    owner_zone = apply_thesis_ownership(second, snap)
    assert owner_zone is not None
    assert owner_zone.zone_id == "SELL_ORIGINAL"
    assert owner_zone.core_low == 104.0
    assert owner_zone.core_high == 105.0
    assert second.selected_zone_id == "SELL_ORIGINAL"
    assert second.execution_policy["active_thesis"]["owner_zone_id"] == "SELL_ORIGINAL"
