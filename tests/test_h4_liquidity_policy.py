from app.engine import Candidate
from app.h4_liquidity_policy import apply_latest_h4_liquidity_policy
from app.models import Analysis, Direction, Grade, LiquidityLevel, MarketSnapshot, Zone, ZoneState


def _snapshot():
    return MarketSnapshot(
        sent_at=1000,
        bid=105.0,
        ask=105.2,
        spread_points=20,
        atr_h1=10.0,
        atr_m15=2.0,
    )


def _analysis(source_tf="H4", zone_id="Z_H4_SELL_1"):
    zone = Zone(
        zone_id=zone_id,
        original_direction=Direction.SELL,
        flip_direction=Direction.BUY,
        setup_type="CONTINUATION",
        source_tf=source_tf,
        grade=Grade.B_PLUS,
        state=ZoneState.ACTIVE,
        core_low=100.0,
        core_high=101.0,
        core_method="WATCH|H4_PARENT_UNREFINED",
        location_score=7.0,
        zone_low=100.0,
        zone_high=103.0,
        touch_count=1,
        invalidation_level=103.0,
        invalidation_rule="test",
    )
    return Analysis(
        analysis_id="A1",
        generated_at=1000,
        snapshot_at=1000,
        zones=[zone],
        liquidity_map=[
            LiquidityLevel(
                label="H4_BSL",
                price=102.0,
                side="ABOVE",
                source_tf="H4",
                distance=3.0,
            )
        ],
        trader_brief="Zones: 0 actionable, 1 watch, 0 context.",
        approved=True,
    )


def test_latest_unmitigated_h4_with_resting_liquidity_is_actionable(monkeypatch):
    import app.h4_liquidity_policy as policy

    monkeypatch.setattr(
        policy,
        "build_candidates",
        lambda s: [
            Candidate(Direction.SELL, 100.0, 101.0, "H4", 100, "H4_PARENT_UNREFINED", [])
        ],
    )
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 0)
    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)

    analysis = _analysis()
    promoted = apply_latest_h4_liquidity_policy(analysis, _snapshot())

    assert len(promoted) == 1
    zone = analysis.zones[0]
    assert zone.core_method.startswith("ACTIONABLE|")
    assert zone.grade == Grade.A
    assert zone.touch_count == 0
    assert analysis.selected_zone_id == zone.zone_id
    assert "LAST_H4_UNMITIGATED" in zone.confluences
    assert "1 actionable, 0 watch" in analysis.trader_brief


def test_h1_refined_h4_parent_also_qualifies(monkeypatch):
    import app.h4_liquidity_policy as policy

    monkeypatch.setattr(
        policy,
        "build_candidates",
        lambda s: [
            Candidate(Direction.SELL, 100.0, 101.0, "H4>H1", 120, "H4_PARENT_H1_REFINEMENT", [])
        ],
    )
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 0)
    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)

    analysis = _analysis("H4>H1", "Z_H4H1_SELL_1")
    promoted = apply_latest_h4_liquidity_policy(analysis, _snapshot())

    assert len(promoted) == 1
    assert analysis.zones[0].source_tf == "H4>H1"
    assert analysis.zones[0].core_method.startswith("ACTIONABLE|")
    assert analysis.zones[0].grade == Grade.A


def test_mitigated_h4_is_not_promoted(monkeypatch):
    import app.h4_liquidity_policy as policy

    monkeypatch.setattr(
        policy,
        "build_candidates",
        lambda s: [
            Candidate(Direction.SELL, 100.0, 101.0, "H4", 100, "H4_PARENT_UNREFINED", [])
        ],
    )
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 1)
    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)

    analysis = _analysis()
    promoted = apply_latest_h4_liquidity_policy(analysis, _snapshot())

    assert promoted == []
    assert analysis.zones[0].core_method.startswith("WATCH|")
    assert analysis.selected_zone_id == ""
