from app.models import Analysis, Bar, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.target_revalidation import target_ladder_truth


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


def _snapshot(mid: float, bars: list[Bar]) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=2000,
        bid=mid - 0.08,
        ask=mid + 0.08,
        spread_points=16,
        point=0.01,
        atr_m15=4.0,
        atr_h1=20.0,
        xau_m15=bars,
    )


def test_consumed_targets_do_not_reopen_after_price_retraces():
    zone = _sell_zone()
    analysis = Analysis(
        analysis_id="A1",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
    )
    bars = [
        _bar(900, 4300.0, 4302.0, 4298.0, 4300.0),
        _bar(1050, 4295.0, 4297.0, 4288.0, 4290.0),
        _bar(1200, 4288.0, 4290.0, 4280.0, 4283.0),
        _bar(1350, 4275.0, 4277.0, 4268.0, 4270.0),
    ]
    # Price has retraced back above TP3, but TP3 was already traded through.
    truth = target_ladder_truth(analysis, zone, _snapshot(4273.20, bars))

    states = {x["label"]: x["state"] for x in truth["objectives"]}
    assert states["TP1"] == "BEHIND_ACTIVATION_PRICE"
    assert states["TP2"] == "BEHIND_ACTIVATION_PRICE"
    assert states["TP3"] == "COMPLETED"
    assert truth["open_targets"] == []
    assert truth["authority_safe"] is False
    assert truth["remap_required"] is True
    assert truth["status"] == "REMAP_REQUIRED"


def test_fresh_open_target_remains_authority_safe():
    zone = _sell_zone()
    zone.original_target1 = 4261.34
    zone.original_target2 = 0.0
    zone.original_target3 = 0.0
    analysis = Analysis(
        analysis_id="A2",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
    )
    bars = [
        _bar(900, 4300.0, 4302.0, 4298.0, 4300.0),
        _bar(1050, 4290.0, 4291.0, 4280.0, 4285.0),
        _bar(1200, 4285.0, 4287.0, 4270.0, 4275.0),
    ]
    truth = target_ladder_truth(analysis, zone, _snapshot(4273.20, bars))

    assert truth["open_targets"] == [4261.34]
    assert truth["authority_safe"] is True
    assert truth["status"] == "OPEN_TARGETS_AVAILABLE"


def test_missing_publication_history_blocks_new_authority():
    zone = _sell_zone()
    zone.notes = ["geometry_published_at:1000"]
    analysis = Analysis(
        analysis_id="A3",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
    )
    # History begins after publication, so earlier target consumption is unknowable.
    bars = [_bar(1200, 4300.0, 4302.0, 4298.0, 4300.0)]
    truth = target_ladder_truth(analysis, zone, _snapshot(4305.0, bars))

    assert truth["history_complete"] is False
    assert truth["authority_safe"] is False
    assert truth["status"] == "HISTORY_UNVERIFIED_BLOCK"


def test_owner_targets_use_frozen_activation_anchor():
    zone = _sell_zone()
    zone.original_target1 = 4291.50
    zone.original_target2 = 4261.34
    zone.original_target3 = 0.0
    analysis = Analysis(
        analysis_id="A4",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        execution_policy={
            "active_thesis": {
                "locked": True,
                "owner_zone_id": zone.zone_id,
                "direction": "SELL",
                "ownership_acquired_at": 1100,
                "ownership_anchor_price": 4285.0,
                "best_price": 4270.0,
                "target1_hit_at": 0,
                "target2_hit_at": 0,
                "target3_hit_at": 0,
            }
        },
    )
    bars = [
        _bar(900, 4300.0, 4302.0, 4298.0, 4300.0),
        _bar(1200, 4283.0, 4284.0, 4270.0, 4272.0),
    ]
    truth = target_ladder_truth(analysis, zone, _snapshot(4273.20, bars))
    states = {x["label"]: x["state"] for x in truth["objectives"]}

    assert states["TP1"] == "BEHIND_ACTIVATION_PRICE"
    assert states["TP2"] == "OPEN"
    assert truth["open_targets"] == [4261.34]
    assert truth["authority_safe"] is True
