import asyncio

from app import service
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState


def _snapshot():
    return MarketSnapshot(
        sent_at=2_000,
        bid=100.0,
        ask=100.16,
        spread_points=16,
        point=0.01,
        atr_h1=8.0,
        atr_m15=2.0,
    )


def _zone():
    return Zone(
        zone_id="Z1",
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf="H4>H1",
        grade=Grade.A_PLUS,
        state=ZoneState.ACTIVE,
        core_low=104.0,
        core_high=105.0,
        core_method="M1_READY|TEST",
        location_score=9.0,
        zone_low=95.0,
        zone_high=106.0,
        touch_count=1,
        independent_confluence_count=6,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "BSL_IN_MARKED_ZONE"],
        source_ts=777,
        invalidation_level=106.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=90.0,
        original_target2=85.0,
        clear_run=10.0,
    )


def test_nonexception_no_provider_uses_paper_fallback_without_deadlocking(monkeypatch):
    snap = _snapshot()
    zone = _zone()
    analysis = Analysis(
        analysis_id="A1",
        generated_at=2_000,
        snapshot_at=2_000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=False,
    )

    monkeypatch.setattr(service, "latest_snapshot", lambda: snap)
    monkeypatch.setattr(service, "build_prompt_analysis", lambda s, now: analysis)
    for name in (
        "register_analysis_zones",
        "apply_dynamic_continuation_rezone",
        "apply_prompt_confirmation_contract",
        "_stamp_prompt_selection_contract",
        "apply_secondary_zone_policy",
        "apply_liquidity_objective_policy",
        "update_zone_reactions",
        "hard_release_stale_thesis",
        "save_analysis",
        "attach_lifecycle",
        "capture_cloud_candidates",
        "audit",
    ):
        monkeypatch.setattr(service, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "apply_thesis_ownership", lambda a, s: None)
    monkeypatch.setattr(service, "promote_watch_to_m1_ready", lambda a, s: zone)
    monkeypatch.setattr(
        service,
        "_stamp_execution_authority",
        lambda a, ready, lr: "HTF_CORE_HANDOFF",
    )
    monkeypatch.setattr(
        service,
        "build_execution_overlay",
        lambda s, a, reason: {"regime": {"name": "RANGE"}},
    )
    monkeypatch.setattr(service, "regime_brief", lambda overlay: "regime test")

    async def no_provider(a, s):
        return False, "AI required but no provider configured.", ["AI_PROVIDER_UNAVAILABLE"], "NONE"

    monkeypatch.setattr(service, "validate_with_ai", no_provider)
    monkeypatch.setattr(
        service,
        "_acquire_final_ownership",
        lambda a, s, authority, lr: (authority, {"reaction_key": "OWNER"}),
    )

    out = asyncio.run(service.run_analysis("TEST_NO_PROVIDER"))
    assert out.approved is True
    assert out.ai_approved is False
    fallback = out.execution_policy["paper_ai_fallback"]
    assert fallback["active"] is True
    assert fallback["authority"] == "HTF_CORE_HANDOFF"
    assert fallback["real_money_allowed"] is False
    assert "AI_PROVIDER_UNAVAILABLE_ADVISORY_PAPER_ONLY" in out.guards


def test_real_ai_rejection_does_not_use_paper_fallback(monkeypatch):
    snap = _snapshot()
    zone = _zone()
    analysis = Analysis(
        analysis_id="A2",
        generated_at=2_000,
        snapshot_at=2_000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=False,
    )

    monkeypatch.setattr(service, "latest_snapshot", lambda: snap)
    monkeypatch.setattr(service, "build_prompt_analysis", lambda s, now: analysis)
    for name in (
        "register_analysis_zones",
        "apply_dynamic_continuation_rezone",
        "apply_prompt_confirmation_contract",
        "_stamp_prompt_selection_contract",
        "apply_secondary_zone_policy",
        "apply_liquidity_objective_policy",
        "update_zone_reactions",
        "hard_release_stale_thesis",
        "save_analysis",
        "attach_lifecycle",
        "capture_cloud_candidates",
        "audit",
    ):
        monkeypatch.setattr(service, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "apply_thesis_ownership", lambda a, s: None)
    monkeypatch.setattr(service, "promote_watch_to_m1_ready", lambda a, s: zone)
    monkeypatch.setattr(service, "_stamp_execution_authority", lambda a, ready, lr: "HTF_CORE_HANDOFF")
    monkeypatch.setattr(service, "build_execution_overlay", lambda s, a, reason: {"regime": {"name": "RANGE"}})
    monkeypatch.setattr(service, "regime_brief", lambda overlay: "regime test")

    async def explicit_reject(a, s):
        return False, "Rejected by configured validator.", ["STRUCTURAL_CONCERN"], "GEMINI:test"

    monkeypatch.setattr(service, "validate_with_ai", explicit_reject)
    monkeypatch.setattr(service, "_acquire_final_ownership", lambda a, s, authority, lr: (authority, None))

    out = asyncio.run(service.run_analysis("TEST_AI_REJECTION"))
    assert out.approved is False
    assert "paper_ai_fallback" not in out.execution_policy
