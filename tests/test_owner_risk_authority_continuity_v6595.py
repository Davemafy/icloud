from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app.professional_zone_execution_separation import apply_execution_separation
from app.risk_matrix import original_risk_pct, zone_risk_context
from app.thesis_ownership_policy import _enrich_legacy_owner_snapshot


def _rich_buy() -> Zone:
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
        core_method="M1_READY|MASTER_SNIPER_SOURCE_EXACT|PROMPT_H4_PARENT_H1_REFINEMENT",
        location_score=11.01,
        zone_low=4253.42,
        zone_high=4275.79,
        touch_count=0,
        independent_confluence_count=4,
        confluences=[
            "LIQUIDITY_IN_MARKED_ZONE",
            "SSL_IN_MARKED_ZONE",
            "SOURCE_CANDLE_ANCHORED",
            "NO_SYNTHETIC_ZONE_EXPANSION",
        ],
        source_ts=1790000000,
        invalidation_level=4253.42,
        invalidation_rule="M15_ACCEPTED_INVALIDATION",
        original_target1=4285.0,
        original_target2=4303.32,
        original_target3=4308.22,
        clear_run=9.21,
        countertrend=True,
    )


def test_legacy_owner_enrichment_restores_countertrend_risk_and_structure():
    rich = _rich_buy()
    legacy = rich.model_copy(
        update={
            "setup_type": "CONTINUATION",
            "core_method": "PERSISTED_OWNER_MIRROR_LEGACY",
            "location_score": 0.0,
            "zone_low": rich.core_low,
            "zone_high": rich.core_high,
            "independent_confluence_count": 2,
            "confluences": ["PERSISTED_EXECUTION_OWNER", "MT5_OWNER_MIRROR_RECOVERY"],
            "clear_run": 0.0,
            "countertrend": False,
        },
        deep=True,
    )
    owner = {
        "reaction_key": "",
        "ownership_zone_id": rich.zone_id,
        "latest_zone_id": rich.zone_id,
        "direction": "BUY",
        "source_tf": rich.source_tf,
        "source_ts": rich.source_ts,
        "core_low": rich.core_low,
        "core_high": rich.core_high,
        "target1": 4285.0,
        "target2": 4303.32,
        "target3": 4308.65,
    }
    analysis = Analysis(
        analysis_id="A_ENRICH",
        generated_at=1790549000,
        snapshot_at=1790549000,
        overall_bias=Direction.SELL,
        zones=[rich],
        selected_zone_id=rich.zone_id,
        approved=True,
        ai_approved=True,
    )

    enriched = _enrich_legacy_owner_snapshot(analysis, owner, legacy)
    assert enriched is not None
    assert enriched.core_method != "PERSISTED_OWNER_MIRROR_LEGACY"
    assert enriched.setup_type == "REVERSAL"
    assert enriched.countertrend is True
    assert "LIQUIDITY_IN_MARKED_ZONE" in enriched.confluences
    assert enriched.clear_run == 9.21
    assert enriched.original_target3 == 4308.65  # owner lifecycle remains frozen
    assert zone_risk_context(enriched) == "COUNTERTREND"
    assert original_risk_pct(enriched) == 0.150


def test_spread_hold_preserves_earned_authority_but_keeps_watch_only(monkeypatch):
    zone = _rich_buy()
    analysis = Analysis(
        analysis_id="A_SAFE",
        generated_at=1790549000,
        snapshot_at=1790549000,
        overall_bias=Direction.SELL,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )
    snapshot = MarketSnapshot(
        sent_at=1790549000,
        bid=4261.80,
        ask=4262.39,
        spread_points=59.0,
        point=0.01,
        atr_h1=20.0,
        atr_m15=6.0,
        kind="HISTORICAL_REPLAY",
    )
    monkeypatch.setattr(
        "app.professional_zone_execution_separation.history_audit",
        lambda _snapshot: (True, []),
    )
    monkeypatch.setattr(
        "app.professional_zone_execution_separation.conservative_runway",
        lambda _zone, *args, **kwargs: (10.0, 5.0, True),
    )
    text = (
        "ea_mode=DUAL_BRANCH\n"
        "zone_id=PZ_H4H1_BUY_6\n"
        "execution_authority=HTF_CORE_HANDOFF\n"
    )
    out = dict(
        line.split("=", 1)
        for line in apply_execution_separation(text, analysis, snapshot).splitlines()
        if "=" in line
    )
    assert out["ea_mode"] == "WATCH_ONLY"
    assert out["execution_authority"] == "HTF_CORE_HANDOFF"
    assert out["safety_hold_preserves_authority"] == "1"
    assert "SPREAD_SAFETY_HOLD" in out["separation_guard"]
