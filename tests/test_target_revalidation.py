from app.models import Analysis, Bar, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.target_revalidation import activation_target_truth, target_ladder_truth


def _bar(ts, open_, high, low, close):
    return Bar(ts=ts, open=open_, high=high, low=low, close=close)


def _sell_zone() -> Zone:
    return Zone(
        zone_id="PZ_H1_SELL_16",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H1",
        grade=Grade.A,
        state=ZoneState.ACTIVE,
        core_low=4303.77,
        core_high=4309.77,
        core_method="ARMED",
        location_score=4.22,
        zone_low=4302.19,
        zone_high=4324.19,
        source_ts=1,
        invalidation_level=4324.19,
        invalidation_rule="M15 accepted invalidation",
        original_target1=4291.50,
        original_target2=4282.39,
        original_target3=4272.62,
        notes=["geometry_published_at:1000"],
    )


def _analysis(zone: Zone, execution_policy=None) -> Analysis:
    return Analysis(
        analysis_id="A1",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        execution_policy=execution_policy or {},
    )


def _snapshot(mid: float, bars=None) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=2000,
        bid=mid - 0.08,
        ask=mid + 0.08,
        spread_points=16,
        point=0.01,
        atr_m15=4.0,
        atr_h1=20.0,
        xau_m15=list(bars or []),
    )


def test_unactivated_sell_targets_remain_planned_even_when_price_is_below_them():
    zone = _sell_zone()
    bars = [
        _bar(1050, 4295.0, 4297.0, 4288.0, 4290.0),
        _bar(1200, 4288.0, 4290.0, 4280.0, 4283.0),
        _bar(1350, 4275.0, 4277.0, 4268.0, 4270.0),
    ]
    truth = target_ladder_truth(_analysis(zone), zone, _snapshot(4273.20, bars))

    assert truth["status"] == "PLANNED_NOT_ACTIVATED"
    assert truth["activated"] is False
    assert truth["planned_targets"] == [4291.5, 4282.39, 4272.62]
    assert truth["open_targets"] == []
    assert truth["completed_targets"] == []
    assert truth["behind_activation_targets"] == []
    assert truth["remap_required"] is False
    assert truth["pre_activation_crossings_consume_targets"] is False
    assert {x["state"] for x in truth["objectives"]} == {"PLANNED"}


def test_same_sell_targets_become_open_when_zone_later_activates_near_core():
    zone = _sell_zone()
    truth = activation_target_truth(
        zone,
        _snapshot(4305.0),
        4304.92,
        activation_ts=2000,
        reference_basis="LIVE_EXECUTION_HANDOFF_REFERENCE",
    )

    assert truth["status"] == "OPEN_TARGETS_AVAILABLE"
    assert truth["open_targets"] == [4291.5, 4282.39, 4272.62]
    assert truth["behind_activation_targets"] == []
    assert truth["authority_safe"] is True


def test_only_targets_behind_actual_activation_price_are_unavailable():
    zone = _sell_zone()
    truth = activation_target_truth(
        zone,
        _snapshot(4280.0),
        4279.92,
        activation_ts=2000,
        reference_basis="LIVE_EXECUTION_HANDOFF_REFERENCE",
    )

    states = {x["label"]: x["state"] for x in truth["objectives"]}
    assert states["TP1"] == "BEHIND_ACTIVATION_PRICE"
    assert states["TP2"] == "BEHIND_ACTIVATION_PRICE"
    assert states["TP3"] == "OPEN"
    assert truth["open_targets"] == [4272.62]
    assert truth["authority_safe"] is True


def test_active_owner_target_progress_starts_from_ownership_not_publication():
    zone = _sell_zone()
    analysis = _analysis(
        zone,
        {
            "active_thesis": {
                "locked": True,
                "owner_zone_id": zone.zone_id,
                "direction": "SELL",
                "ownership_acquired_at": 1500,
                "ownership_anchor_price": 4305.0,
                "best_price": 4280.0,
                "target1_hit_at": 0,
                "target2_hit_at": 0,
                "target3_hit_at": 0,
            }
        },
    )
    truth = target_ladder_truth(analysis, zone, _snapshot(4281.0))

    states = {x["label"]: x["state"] for x in truth["objectives"]}
    assert states["TP1"] == "COMPLETED"
    assert states["TP2"] == "COMPLETED"
    assert states["TP3"] == "OPEN"
    assert truth["open_targets"] == [4272.62]
    assert truth["completed_targets"] == [4291.5, 4282.39]
    assert truth["status"] == "ACTIVE_TARGETS_OPEN"


def test_no_open_target_at_actual_activation_requires_remap():
    zone = _sell_zone()
    truth = activation_target_truth(
        zone,
        _snapshot(4260.0),
        4259.92,
        activation_ts=2000,
    )

    assert truth["open_targets"] == []
    assert truth["authority_safe"] is False
    assert truth["remap_required"] is True
    assert truth["status"] == "REMAP_REQUIRED_AT_ACTIVATION"
