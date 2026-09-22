from app import institutional_two_zone as policy
from app.models import (
    Analysis,
    Direction,
    Grade,
    LiquidityLevel,
    MarketSnapshot,
    ZoneState,
)


def _snapshot(mid: float = 95.0, atr_h1: float = 10.0) -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=1_800_000_000,
        bid=mid - 0.08,
        ask=mid + 0.08,
        spread_points=16,
        point=0.01,
        atr_h1=atr_h1,
        atr_m15=2.0,
    )


def _analysis(liquidity) -> Analysis:
    return Analysis(
        analysis_id="A_TEST",
        generated_at=1_800_000_000,
        snapshot_at=1_800_000_000,
        overall_bias=Direction.SELL,
        liquidity_map=liquidity,
    )


def _sell_candidate() -> policy.PromptCandidate:
    return policy.PromptCandidate(
        direction=Direction.SELL,
        source_tf="H4",
        source_ts=1_799_000_000,
        core_low=104.0,
        core_high=106.0,
        zone_low=100.0,
        zone_high=110.0,
        strength=2.2,
        fvg=True,
        source_kind="DISPLACEMENT_BOS_SOURCE",
        volume_expansion=False,
        method="PROMPT_H4_SOURCE_CANDLE",
    )


def _patch_common(monkeypatch, candidate, touches=0):
    monkeypatch.setattr(policy, "_build_candidates", lambda snapshot: [candidate])
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: touches)
    monkeypatch.setattr(policy, "evaluate_zone_state", lambda *args, **kwargs: ZoneState.ACTIVE)
    monkeypatch.setattr(policy, "_location_score", lambda *args, **kwargs: 8.0)
    monkeypatch.setattr(
        policy,
        "_targets",
        lambda direction, ref, liq: [90.0, 80.0, 70.0, 60.0]
        if direction == Direction.SELL
        else [120.0, 130.0, 140.0, 150.0],
    )
    monkeypatch.setattr(policy, "_dxy", lambda snapshot: Direction.NEUTRAL)


def test_sell_zone_keeps_bsl_inside_professional_source_tf_envelope(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate)
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=108.0, side="ABOVE", source_tf="H4", distance=13.0)
    ])

    zones = policy.apply_two_zone_institutional_map(analysis, _snapshot())

    assert len(zones) == 1
    zone = zones[0]
    # Professional H4 geometry may expand beyond the raw source candle so the
    # structural BSL and the required 50-pip distal raid room both fit inside.
    assert zone.zone_low == 95.0
    assert zone.zone_high == 113.0
    assert zone.zone_low <= 108.0 <= zone.zone_high
    assert zone.zone_high - 108.0 >= 5.0
    assert "LIQUIDITY_IN_MARKED_ZONE" in zone.confluences
    assert "BSL_IN_MARKED_ZONE" in zone.confluences
    assert analysis.execution_policy["public_zone_map"]["map_count"] == 1


def test_sell_candidate_is_rejected_when_bsl_is_not_inside_zone(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate)
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=120.0, side="ABOVE", source_tf="H4", distance=25.0)
    ])

    zones = policy.apply_two_zone_institutional_map(analysis, _snapshot())

    assert zones == []
    diag = analysis.execution_policy["public_zone_map"]["rejected_diagnostics"]["sell"]["strongest_rejected"]
    assert diag["rejection_code"] == "MISSING_BSL_IN_MARKED_ZONE"


def test_distance_does_not_delete_a_valid_prompt_zone(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate)
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=108.0, side="ABOVE", source_tf="H4", distance=108.0)
    ])

    zones = policy.apply_two_zone_institutional_map(
        analysis,
        _snapshot(mid=0.0, atr_h1=1.0),
    )

    assert len(zones) == 1
    assert analysis.execution_policy["public_zone_map"]["distance_is_not_a_hard_zone_filter"] is True


def test_strong_second_mitigation_can_remain_a_grade_at_reduced_risk(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate, touches=2)
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=108.0, side="ABOVE", source_tf="H4", distance=13.0)
    ])

    zones = policy.apply_two_zone_institutional_map(analysis, _snapshot())

    assert len(zones) == 1
    assert zones[0].grade == Grade.A
    assert zones[0].core_method.startswith("ARMED|")
    assert analysis.selected_zone_id == zones[0].zone_id


def test_m15_accepted_invalidation_removes_zone(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate)
    monkeypatch.setattr(
        policy,
        "evaluate_zone_state",
        lambda *args, **kwargs: ZoneState.FAILED_FLIP_CANDIDATE,
    )
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=108.0, side="ABOVE", source_tf="H4", distance=13.0)
    ])

    zones = policy.apply_two_zone_institutional_map(analysis, _snapshot())

    assert zones == []
    diag = analysis.execution_policy["public_zone_map"]["rejected_diagnostics"]["sell"]["strongest_rejected"]
    assert diag["rejection_code"] == "M15_ACCEPTED_INVALIDATION"


def test_atr_proximity_does_not_label_sell_zone_interacting_before_live_core_contact(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate, touches=1)
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=108.0, side="ABOVE", source_tf="H4", distance=4.0)
    ])
    snap = _snapshot(mid=103.95)

    zones = policy.apply_two_zone_institutional_map(analysis, snap)

    assert len(zones) == 1
    zone = zones[0]
    assert snap.ask < zone.core_low
    assert policy.primary_zone_approaching(zone, snap) is True
    assert policy.primary_zone_interacting(zone, snap) is False
    assert zone.core_method.startswith("ARMED|")
    assert analysis.execution_policy["public_zone_map"]["sell"]["state"] == "ARMED"


def test_live_quote_overlap_with_core_labels_zone_interacting(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate, touches=1)
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=108.0, side="ABOVE", source_tf="H4", distance=4.0)
    ])
    snap = _snapshot(mid=104.50)

    zones = policy.apply_two_zone_institutional_map(analysis, snap)

    assert len(zones) == 1
    zone = zones[0]
    assert snap.ask >= zone.core_low
    assert snap.bid <= zone.core_high
    assert policy.primary_zone_interacting(zone, snap) is True
    assert zone.core_method.startswith("INTERACTING|")
    assert analysis.execution_policy["public_zone_map"]["sell"]["state"] == "INTERACTING"


def _buy_reversal_candidate() -> policy.PromptCandidate:
    return policy.PromptCandidate(
        direction=Direction.BUY,
        source_tf="H4>H1",
        source_ts=1_799_000_000,
        core_low=94.0,
        core_high=96.0,
        zone_low=90.0,
        zone_high=98.0,
        strength=2.4,
        fvg=False,
        source_kind="LIQUIDITY_SWEEP_REJECTION+LIQUIDITY_SWEEP_REJECTION",
        volume_expansion=True,
        method="PROMPT_H4_PARENT_H1_REFINEMENT",
    )


def test_countertrend_uses_dedicated_reversal_model_and_can_be_a_plus(monkeypatch):
    candidate = _buy_reversal_candidate()
    _patch_common(monkeypatch, candidate, touches=1)
    analysis = _analysis([
        LiquidityLevel(label="H4_SSL", price=92.0, side="BELOW", source_tf="H4", distance=3.0)
    ])
    analysis.overall_bias = Direction.SELL

    zones = policy.apply_two_zone_institutional_map(analysis, _snapshot(mid=100.0))

    assert len(zones) == 1
    zone = zones[0]
    assert zone.countertrend is True
    assert zone.setup_type == "REVERSAL"
    assert zone.grade == Grade.A_PLUS
    assert zone.touch_count == 1
    assert any(x == "grade_context:COUNTERTREND_REVERSAL" for x in zone.notes)


def test_countertrend_second_qualified_mitigation_is_a_not_forced_bplus(monkeypatch):
    candidate = _buy_reversal_candidate()
    _patch_common(monkeypatch, candidate, touches=2)
    analysis = _analysis([
        LiquidityLevel(label="H4_SSL", price=92.0, side="BELOW", source_tf="H4", distance=3.0)
    ])
    analysis.overall_bias = Direction.SELL

    zones = policy.apply_two_zone_institutional_map(analysis, _snapshot(mid=100.0))

    assert len(zones) == 1
    assert zones[0].grade == Grade.A
    assert zones[0].touch_count == 2


def test_core_edge_chop_is_one_qualified_mitigation_until_envelope_exit():
    bars = [
        policy.Bar(ts=200, open=100.2, high=100.8, low=99.8, close=100.4),
        policy.Bar(ts=300, open=101.2, high=101.4, low=101.1, close=101.2),
        policy.Bar(ts=400, open=100.9, high=101.1, low=99.9, close=100.3),
        policy.Bar(ts=500, open=101.3, high=101.5, low=101.1, close=101.3),
        policy.Bar(ts=600, open=100.8, high=101.0, low=99.9, close=100.5),
    ]

    mitigations = policy._qualified_mitigations(
        100.0, 101.0, 98.0, 103.0, 100, bars, raw_touch_episodes=3
    )

    assert mitigations == 1

    bars.extend(
        [
            policy.Bar(ts=700, open=103.2, high=104.2, low=103.1, close=104.0),
            policy.Bar(ts=800, open=101.1, high=101.2, low=100.1, close=100.6),
        ]
    )
    mitigations = policy._qualified_mitigations(
        100.0, 101.0, 98.0, 103.0, 100, bars, raw_touch_episodes=4
    )
    assert mitigations == 2
