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
    monkeypatch.setattr(
        policy,
        "audit_directional_mitigations",
        lambda *args, **kwargs: {
            "qualified_mitigations": touches,
            "raw_core_contact_episodes_before_invalidation": touches,
            "history_complete": True,
            "history_start_ts": candidate.source_ts,
            "history_required_from_ts": candidate.source_ts,
            "history_gap_reason": "",
            "events": [],
            "invalidated_at": 0,
            "invalidation_reason": "",
            "expected_approach_side": "BELOW" if candidate.direction == Direction.SELL else "ABOVE",
            "expected_reaction_exit_side": "BELOW" if candidate.direction == Direction.SELL else "ABOVE",
            "distal_invalidation_side": "ABOVE" if candidate.direction == Direction.SELL else "BELOW",
            "counting_stopped": False,
        },
    )
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


def test_historical_accepted_invalidation_stops_old_zone_before_latest_state_check(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate, touches=0)
    monkeypatch.setattr(
        policy,
        "audit_directional_mitigations",
        lambda *args, **kwargs: {
            "qualified_mitigations": 1,
            "raw_core_contact_episodes_before_invalidation": 1,
            "history_complete": True,
            "history_start_ts": 100,
            "history_required_from_ts": 100,
            "history_gap_reason": "",
            "events": [
                {
                    "event_type": "INVALIDATION",
                    "qualified": False,
                    "qualified_index": 0,
                    "qualified_count_before": 1,
                    "armed_at": 200,
                    "approach_side": "BELOW",
                    "core_touched_at": 0,
                    "qualified_at": 0,
                    "bar_ts": 900,
                    "reason": "M15_SINGLE_ACCEPTED_BODY",
                }
            ],
            "invalidated_at": 900,
            "invalidation_reason": "M15_SINGLE_ACCEPTED_BODY",
            "expected_approach_side": "BELOW",
            "expected_reaction_exit_side": "BELOW",
            "distal_invalidation_side": "ABOVE",
            "counting_stopped": True,
        },
    )
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=108.0, side="ABOVE", source_tf="H4", distance=13.0)
    ])

    zones = policy.apply_two_zone_institutional_map(analysis, _snapshot())

    assert zones == []
    diag = analysis.execution_policy["public_zone_map"]["rejected_diagnostics"]["sell"]["strongest_rejected"]
    assert diag["rejection_code"] == "HISTORICAL_M15_ACCEPTED_INVALIDATION"
    assert diag["mitigation_invalidated_at"] == 900
    assert diag["mitigation_audit"]["counting_stopped"] is True


def test_atr_proximity_does_not_label_sell_zone_interacting_before_live_core_contact(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate, touches=1)
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=108.0, side="ABOVE", source_tf="H4", distance=4.0)
    ])
    # Keep the quote just above the core but within the 0.30 x M15 ATR
    # approach buffer. This remains valid under the installed V659 H4 geometry.
    snap = _snapshot(mid=106.35)

    zones = policy.apply_two_zone_institutional_map(analysis, snap)

    assert len(zones) == 1
    zone = zones[0]
    # Prove there is no live quote/core overlap without assuming which side
    # of the core current price is on. The runtime interaction predicate is
    # intentionally direction-agnostic geometry overlap.
    assert snap.ask < zone.core_low or snap.bid > zone.core_high
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


def test_sell_mitigation_requires_below_core_below_complete_cycle():
    bars = [
        # Arm from the correct SELL approach side.
        policy.Bar(ts=200, open=97.5, high=97.9, low=97.0, close=97.5),
        # Touch the core from below but remain inside the envelope.
        policy.Bar(ts=300, open=99.0, high=100.5, low=98.8, close=100.2),
        policy.Bar(ts=400, open=100.2, high=100.9, low=99.7, close=100.4),
        # Only this closed return below the envelope completes mitigation #1.
        policy.Bar(ts=500, open=99.0, high=99.2, low=97.0, close=97.5),
        # A second correct approach/reaction cycle.
        policy.Bar(ts=600, open=98.0, high=100.4, low=97.7, close=100.1),
        policy.Bar(ts=700, open=99.0, high=99.1, low=97.1, close=97.4),
    ]

    audit = policy.audit_directional_mitigations(
        Direction.SELL, 100.0, 101.0, 98.0, 103.0, 100, bars
    )

    assert audit["qualified_mitigations"] == 2
    qualified = [x for x in audit["events"] if x.get("qualified")]
    assert [x["core_touched_at"] for x in qualified] == [300, 600]
    assert [x["qualified_at"] for x in qualified] == [500, 700]
    assert all(x["approach_side"] == "BELOW" for x in qualified)


def test_sell_core_contact_from_above_does_not_consume_freshness():
    bars = [
        policy.Bar(ts=200, open=104.0, high=104.3, low=103.5, close=104.0),
        policy.Bar(ts=300, open=103.4, high=103.7, low=100.4, close=100.7),
        policy.Bar(ts=400, open=100.7, high=101.0, low=99.7, close=100.2),
        policy.Bar(ts=500, open=99.0, high=99.2, low=97.0, close=97.6),
    ]

    audit = policy.audit_directional_mitigations(
        Direction.SELL, 100.0, 101.0, 98.0, 103.0, 100, bars
    )

    assert audit["qualified_mitigations"] == 0
    wrong = [x for x in audit["events"] if x.get("reason") == "WRONG_APPROACH_SIDE"]
    assert len(wrong) == 1
    assert wrong[0]["approach_side"] == "ABOVE"


def test_buy_mitigation_requires_above_core_above_complete_cycle():
    bars = [
        policy.Bar(ts=200, open=104.0, high=104.2, low=103.5, close=104.0),
        policy.Bar(ts=300, open=102.5, high=103.1, low=100.5, close=100.8),
        policy.Bar(ts=400, open=101.0, high=103.5, low=100.2, close=103.4),
    ]

    audit = policy.audit_directional_mitigations(
        Direction.BUY, 100.0, 101.0, 98.0, 103.0, 100, bars
    )

    assert audit["qualified_mitigations"] == 1
    event = next(x for x in audit["events"] if x.get("qualified"))
    assert event["approach_side"] == "ABOVE"
    assert event["core_touched_at"] == 300
    assert event["qualified_at"] == 400


def test_exhausted_countertrend_keeps_structural_grade_separate_from_current_execution_grade(monkeypatch):
    candidate = _buy_reversal_candidate()
    _patch_common(monkeypatch, candidate, touches=8)
    analysis = _analysis([
        LiquidityLevel(label="H4_SSL", price=92.0, side="BELOW", source_tf="H4", distance=3.0)
    ])
    analysis.overall_bias = Direction.SELL

    zones = policy.apply_two_zone_institutional_map(analysis, _snapshot(mid=100.0))

    assert len(zones) == 1
    zone = zones[0]
    assert zone.grade == Grade.B_PLUS
    assert zone.touch_count == 8
    assert "structural_grade:A+" in zone.notes
    assert "current_execution_grade:B+" in zone.notes
    assert "grade_degrade_reason:EXHAUSTED_3PLUS_QUALIFIED_MITIGATIONS" in zone.notes
    public = analysis.execution_policy["public_zone_map"]["buy"]
    assert public["structural_grade"] == "A+"
    assert public["grade"] == "B+"
    assert public["qualified_mitigations"] == 8
    assert public["grade_degrade_reason"] == "EXHAUSTED_3PLUS_QUALIFIED_MITIGATIONS"


def test_mitigation_ledger_records_grade_transition_only_when_cycle_completes():
    candidate = _sell_candidate()
    base_audit = {
        "qualified_mitigations": 2,
        "invalidated_at": 0,
        "invalidation_reason": "",
        "events": [
            {
                "event_type": "MITIGATION",
                "qualified": True,
                "qualified_index": 1,
                "qualified_count_before": 0,
                "armed_at": 200,
                "approach_side": "BELOW",
                "core_touched_at": 300,
                "qualified_at": 400,
                "reason": "DIRECTIONAL_CORE_REACTION_COMPLETE",
            },
            {
                "event_type": "MITIGATION",
                "qualified": True,
                "qualified_index": 2,
                "qualified_count_before": 1,
                "armed_at": 500,
                "approach_side": "BELOW",
                "core_touched_at": 600,
                "qualified_at": 700,
                "reason": "DIRECTIONAL_CORE_REACTION_COMPLETE",
            },
        ],
    }

    ledger = policy._mitigation_grade_ledger(
        base_audit,
        candidate,
        8.0,
        countertrend=False,
        structural_liquidity_tf="H4",
        psy_confluence=True,
    )

    assert ledger["events"][0]["grade_before"] == "A+"
    assert ledger["events"][0]["grade_after"] == "A+"
    assert ledger["events"][0]["grade_changed"] is False
    assert ledger["events"][1]["grade_before"] == "A+"
    assert ledger["events"][1]["grade_after"] == "A"
    assert ledger["events"][1]["grade_changed"] is True


def test_incomplete_m15_freshness_history_forces_structural_a_plus_to_watch_only(monkeypatch):
    candidate = _sell_candidate()
    _patch_common(monkeypatch, candidate, touches=0)
    monkeypatch.setattr(
        policy,
        "audit_directional_mitigations",
        lambda *args, **kwargs: {
            "qualified_mitigations": 0,
            "raw_core_contact_episodes_before_invalidation": 0,
            "history_complete": False,
            "history_start_ts": candidate.source_ts + 7200,
            "history_required_from_ts": candidate.source_ts,
            "history_gap_reason": "M15_HISTORY_STARTS_AFTER_SOURCE_READY",
            "events": [],
            "invalidated_at": 0,
            "invalidation_reason": "",
            "expected_approach_side": "BELOW",
            "expected_reaction_exit_side": "BELOW",
            "distal_invalidation_side": "ABOVE",
            "counting_stopped": False,
        },
    )
    analysis = _analysis([
        LiquidityLevel(label="H4_BSL", price=108.0, side="ABOVE", source_tf="H4", distance=13.0)
    ])

    zones = policy.apply_two_zone_institutional_map(analysis, _snapshot())

    assert len(zones) == 1
    zone = zones[0]
    assert "structural_grade:A+" in zone.notes
    assert zone.grade == Grade.B_PLUS
    assert zone.core_method.startswith("WATCH|")
    assert "grade_degrade_reason:FRESHNESS_HISTORY_INCOMPLETE" in zone.notes
    public = analysis.execution_policy["public_zone_map"]["sell"]
    assert public["mitigation_history_complete"] is False
    assert public["grade"] == "B+"


def test_source_ready_time_is_after_source_candle_close():
    h1 = policy.PromptSource(
        direction=Direction.BUY,
        tf="H1",
        source_ts=1_000,
        core_low=90,
        core_high=91,
        zone_low=89,
        zone_high=92,
        strength=2.0,
        fvg=False,
        source_kind="DISPLACEMENT_BOS_SOURCE",
        volume_expansion=False,
    )
    h4 = policy.PromptSource(
        direction=Direction.SELL,
        tf="H4",
        source_ts=2_000,
        core_low=100,
        core_high=101,
        zone_low=99,
        zone_high=102,
        strength=2.0,
        fvg=False,
        source_kind="DISPLACEMENT_BOS_SOURCE",
        volume_expansion=False,
    )

    assert policy._source_ready_ts(h1) == 1_000 + 3600
    assert policy._source_ready_ts(h4) == 2_000 + 14400


def test_source_ready_prefers_explicit_evidence_ready_timestamp():
    source = policy.PromptSource(
        direction=Direction.SELL,
        tf="H4",
        source_ts=10_000,
        core_low=100,
        core_high=101,
        zone_low=99,
        zone_high=102,
        strength=2.0,
        fvg=True,
        source_kind="DISPLACEMENT_BOS_SOURCE",
        volume_expansion=False,
        ready_ts=30_000,
    )

    assert policy._source_ready_ts(source) == 30_000


def test_countertrend_grade_audit_explains_why_structural_zone_is_a_not_a_plus():
    candidate = _buy_reversal_candidate()
    candidate.strength = 1.8

    audit = policy._grade_audit(
        candidate,
        0,
        7.5,
        countertrend=True,
        structural_liquidity_tf="H4",
        psy_confluence=False,
    )

    assert audit["grade"] == Grade.A
    assert "strength_ge_2" in audit["aplus_missing"]
    assert audit["a_missing"] == []
    assert audit["model"] == "COUNTERTREND_REVERSAL"


def test_trend_grade_audit_exposes_score_and_freshness_gap():
    candidate = _sell_candidate()

    audit = policy._grade_audit(
        candidate,
        2,
        8.0,
        countertrend=False,
        structural_liquidity_tf="H4",
        psy_confluence=True,
    )

    assert audit["grade"] in {Grade.A, Grade.B_PLUS}
    assert audit["model"] == "TREND_CONTINUATION"
    assert "mitigations_le_1" in audit["aplus_missing"]
    assert "score" in audit
