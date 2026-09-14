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
        trader_brief="test",
        approved=True,
    )


def _candidate(source_tf="H4"):
    return Candidate(
        Direction.SELL,
        100.0,
        101.0,
        source_tf,
        100,
        "H4_PARENT_UNREFINED",
        [],
    )


def test_fresh_h4_with_resting_liquidity_is_kept_actionable(monkeypatch):
    import app.h4_liquidity_policy as policy

    monkeypatch.setattr(policy, "build_candidates", lambda s: [_candidate()])
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 0)
    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)

    analysis = _analysis()
    promoted = apply_latest_h4_liquidity_policy(analysis, _snapshot())

    assert len(promoted) == 1
    zone = promoted[0]
    assert zone.core_method.startswith("ACTIONABLE|")
    assert zone.grade == Grade.A
    assert zone.touch_count == 0
    assert analysis.selected_zone_id == ""
    assert "H4_PARENT_AUTHORITY" in zone.confluences
    assert "RESTING_LIQUIDITY" in zone.confluences


def test_single_clean_h4_reaction_remains_valid(monkeypatch):
    import app.h4_liquidity_policy as policy

    monkeypatch.setattr(policy, "build_candidates", lambda s: [_candidate()])
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 1)
    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)

    analysis = _analysis()
    promoted = apply_latest_h4_liquidity_policy(analysis, _snapshot())

    assert len(promoted) == 1
    zone = promoted[0]
    assert zone.touch_count == 1
    assert zone.core_method.startswith("ACTIONABLE|")
    assert "SINGLE_REACTION_STILL_VALID" in zone.confluences


def test_h1_refined_h4_parent_also_qualifies(monkeypatch):
    import app.h4_liquidity_policy as policy

    monkeypatch.setattr(policy, "build_candidates", lambda s: [_candidate("H4>H1")])
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 0)
    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)

    analysis = _analysis("H4>H1", "Z_H4H1_SELL_1")
    promoted = apply_latest_h4_liquidity_policy(analysis, _snapshot())

    assert len(promoted) == 1
    assert promoted[0].source_tf == "H4>H1"
    assert promoted[0].grade == Grade.A


def test_repeatedly_mitigated_h4_is_not_promoted(monkeypatch):
    import app.h4_liquidity_policy as policy

    monkeypatch.setattr(policy, "build_candidates", lambda s: [_candidate()])
    monkeypatch.setattr(policy, "_touches", lambda *args, **kwargs: 2)
    monkeypatch.setattr(policy, "atr", lambda bars: 10.0)

    analysis = _analysis()
    promoted = apply_latest_h4_liquidity_policy(analysis, _snapshot())

    assert promoted == []
    assert analysis.selected_zone_id == ""
