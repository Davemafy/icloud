from app import main
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState


def _zone():
    return Zone(
        zone_id="PZ_H4H1_BUY_6",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="REVERSAL",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=4254.41,
        core_high=4275.79,
        core_method="M1_READY|THESIS_CONTINUATION|REACTION_WINDOW",
        location_score=10.76,
        zone_low=4253.434,
        zone_high=4275.79,
        touch_count=0,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "SSL_IN_MARKED_ZONE"],
        independent_confluence_count=2,
        invalidation_level=4253.434,
        invalidation_rule="M15 accepted invalidation",
        original_target1=4285.0,
        original_target2=4303.32,
        original_target3=4308.65,
        clear_run=9.21,
        countertrend=True,
    )


def _analysis(zone):
    return Analysis(
        analysis_id="A_FINAL_PLAN",
        generated_at=1000,
        snapshot_at=1000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
        execution_policy={
            "execution_authority": {"authority": "HTF_CORE_HANDOFF"},
            "active_thesis": {
                "locked": True,
                "owner_zone_id": zone.zone_id,
                "direction": "BUY",
                "status": "OBJECTIVE_IN_PROGRESS",
                "continuation_authority": True,
                "ownership_authority": "HTF_CORE_HANDOFF",
                "objective_open": True,
                "owner_zone_present": True,
                "ownership_anchor_price": 4287.3,
                "best_price": 4264.0,
            },
        },
    )


def _snapshot():
    return MarketSnapshot(
        sent_at=1000,
        bid=4264.65,
        ask=4264.84,
        spread_points=19.0,
        point=0.01,
        kind="HISTORICAL_REPLAY",
    )


def _patch_common(monkeypatch, analysis, snapshot, sequence_authority):
    monkeypatch.setattr(main, "active_analysis", lambda: analysis)
    monkeypatch.setattr(main, "latest_snapshot", lambda: snapshot)
    monkeypatch.setattr(main, "recent_feedback", lambda _limit: [])
    monkeypatch.setattr(
        main,
        "target_ladder_truth",
        lambda *_args, **_kwargs: {
            "status": "ACTIVE_TARGETS_OPEN",
            "objectives": [],
            "open_targets": [4303.32, 4308.65],
            "completed_targets": [],
            "behind_activation_targets": [4285.0],
            "authority_safe": True,
            "history_complete": True,
            "remap_required": False,
            "activation_reference": 4287.3,
            "activation_reference_basis": "OWNERSHIP_ANCHOR",
        },
    )
    monkeypatch.setattr(
        main,
        "_sequence_debug_snapshot",
        lambda: {
            "online": True,
            "authority": sequence_authority,
            "gate_stage": "ENTRY_CONFIRMATION",
            "gate_reason": "WAITING_FOR_CLOSED_M1_VALUE_REACTION",
            "candidate_model": "SNIPER",
            "open_positions": 0,
        },
    )


def test_journal_uses_final_plan_runway_and_authority(monkeypatch):
    zone = _zone()
    analysis = _analysis(zone)
    snapshot = _snapshot()
    _patch_common(monkeypatch, analysis, snapshot, "HTF_CORE_HANDOFF")
    monkeypatch.setattr(
        main,
        "active_plan_text",
        lambda *_args, **_kwargs: (
            "ea_mode=DUAL_BRANCH\n"
            "execution_authority=HTF_CORE_HANDOFF\n"
            "core_handoff_ready=1\n"
            "usable_runway=27.53000\n"
            "required_runway=10.00000\n"
            "usable_runway_ok=1\n"
            "usable_runway_target=4303.32000\n"
            "usable_runway_target_basis=FINAL_PLAN_NEXT_OPEN_TARGET\n"
            "separation_guard=PASS\n"
        ),
    )

    journal = main._journal_snapshot()
    assert journal["checks"]["clear_run"] is True
    assert journal["checks"]["m1_handoff_ready"] is True
    assert journal["checks"]["fresh_m1_location_ready"] is True
    assert journal["sequence_debug"]["fresh_m1_location_ready"] is True
    assert journal["sequence_debug"]["cloud_authority"] == "HTF_CORE_HANDOFF"
    assert journal["sequence_debug"]["cloud_ea_mode"] == "DUAL_BRANCH"
    assert journal["sequence_debug"]["cloud_usable_runway"] == "27.53000"
    assert journal["sequence_debug"]["cloud_runway_target"] == "4303.32000"
    assert journal["sequence_debug"]["authority_mismatch"] is False


def test_journal_does_not_call_raw_policy_authority_a_mismatch_when_final_plan_is_watch_only(monkeypatch):
    zone = _zone()
    analysis = _analysis(zone)
    snapshot = _snapshot()
    _patch_common(monkeypatch, analysis, snapshot, "NONE")
    monkeypatch.setattr(
        main,
        "active_plan_text",
        lambda *_args, **_kwargs: (
            "ea_mode=WATCH_ONLY\n"
            "execution_authority=NONE\n"
            "core_handoff_ready=1\n"
            "usable_runway=9.21000\n"
            "required_runway=10.00000\n"
            "usable_runway_ok=0\n"
            "usable_runway_target=4285.00000\n"
            "separation_guard=INSUFFICIENT_USABLE_RUNWAY\n"
        ),
    )

    journal = main._journal_snapshot()
    assert journal["checks"]["clear_run"] is False
    assert journal["checks"]["m1_handoff_ready"] is False
    assert journal["checks"]["fresh_m1_location_ready"] is False
    assert journal["sequence_debug"]["fresh_m1_location_ready"] is False
    assert journal["sequence_debug"]["cloud_authority"] == "NONE"
    assert journal["sequence_debug"]["cloud_ea_mode"] == "WATCH_ONLY"
    assert journal["sequence_debug"]["cloud_separation_guard"] == "INSUFFICIENT_USABLE_RUNWAY"
    assert journal["sequence_debug"]["authority_mismatch"] is False


def test_owner_macro_authority_does_not_masquerade_as_fresh_m1_location(monkeypatch):
    zone = _zone()
    analysis = _analysis(zone)
    snapshot = _snapshot()
    _patch_common(monkeypatch, analysis, snapshot, "HTF_CORE_HANDOFF")
    monkeypatch.setattr(
        main,
        "_sequence_debug_snapshot",
        lambda: {
            "online": True,
            "authority": "HTF_CORE_HANDOFF",
            "gate_stage": "LOCATION",
            "gate_reason": "WAITING_FOR_VALID_LOCATION",
            "candidate_model": "NONE",
            "open_positions": 0,
        },
    )
    monkeypatch.setattr(
        main,
        "active_plan_text",
        lambda *_args, **_kwargs: (
            "ea_mode=DUAL_BRANCH\n"
            "execution_authority=HTF_CORE_HANDOFF\n"
            "owner_continuation_ready=1\n"
            "core_handoff_ready=1\n"
            "usable_runway=27.53000\n"
            "required_runway=10.00000\n"
            "usable_runway_ok=1\n"
            "separation_guard=PASS\n"
        ),
    )

    journal = main._journal_snapshot()
    assert journal["checks"]["m1_handoff_ready"] is True
    assert journal["checks"]["fresh_m1_location_ready"] is False
    assert journal["sequence_debug"]["fresh_m1_location_ready"] is False
    assert journal["readiness_score"].endswith("/10")


def test_journal_displays_persisted_acquisition_anchor_without_changing_execution_truth(monkeypatch):
    zone = _zone()
    analysis = _analysis(zone)
    snapshot = _snapshot()
    _patch_common(monkeypatch, analysis, snapshot, "HTF_CORE_HANDOFF")
    monkeypatch.setattr(main, "_dashboard_persisted_owner_anchor", lambda _zone_id: (4258.55, 900))
    monkeypatch.setattr(
        main,
        "active_plan_text",
        lambda *_args, **_kwargs: (
            "ea_mode=DUAL_BRANCH\n"
            "execution_authority=HTF_CORE_HANDOFF\n"
            "owner_continuation_ready=1\n"
            "usable_runway_ok=1\n"
            "separation_guard=PASS\n"
        ),
    )

    journal = main._journal_snapshot()
    assert journal["target_activation_reference"] == 4258.55
    assert journal["target_activation_reference_basis"] == "PERSISTED_OWNERSHIP_ACQUISITION_ANCHOR"
    assert journal["target_ownership_acquired_at"] == 900
    # Execution authority remains sourced from the final plan/Sequence path.
    assert journal["sequence_debug"]["cloud_authority"] == "HTF_CORE_HANDOFF"


def test_finalized_authority_is_macro_handoff_truth_even_without_duplicate_ready_flags(monkeypatch):
    zone = _zone()
    analysis = _analysis(zone)
    snapshot = _snapshot()
    _patch_common(monkeypatch, analysis, snapshot, "HTF_CORE_HANDOFF")
    monkeypatch.setattr(
        main,
        "active_plan_text",
        lambda *_args, **_kwargs: (
            "ea_mode=DUAL_BRANCH\n"
            "execution_authority=HTF_CORE_HANDOFF\n"
            "usable_runway_ok=1\n"
            "separation_guard=PASS\n"
        ),
    )

    journal = main._journal_snapshot()

    assert journal["checks"]["m1_handoff_ready"] is True
    assert journal["sequence_debug"]["cloud_authority"] == "HTF_CORE_HANDOFF"
    assert journal["sequence_debug"]["cloud_ea_mode"] == "DUAL_BRANCH"
