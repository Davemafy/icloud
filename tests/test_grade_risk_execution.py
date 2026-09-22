from app.config import SETTINGS
from app.engine import active_plan_text
from app.execution_safety import guard_plan_text
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState


def _zone(grade: Grade) -> Zone:
    return Zone(
        zone_id="BPLUS_EXEC",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="REVERSAL",
        source_tf="H4>H1",
        grade=grade,
        state=ZoneState.ACTIVE,
        core_low=99.0,
        core_high=101.0,
        core_method="M1_READY|PROMPT_SWEEP_ROOM_GEOMETRY",
        location_score=8.0,
        zone_low=95.0,
        zone_high=105.0,
        touch_count=2 if grade == Grade.B_PLUS else 1,
        independent_confluence_count=4,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "SSL_IN_MARKED_ZONE"],
        source_ts=10,
        invalidation_level=95.0,
        invalidation_rule="M15 accepted invalidation",
        original_target1=110.0,
        original_target2=115.0,
        original_target3=120.0,
        flip_target1=90.0,
        flip_target2=85.0,
        clear_run=9.0,
    )


def _analysis(zone: Zone) -> Analysis:
    return Analysis(
        analysis_id="A_RISK",
        generated_at=100,
        snapshot_at=100,
        overall_bias=Direction.BUY,
        zones=[zone],
        selected_zone_id=zone.zone_id,
        approved=True,
        ai_approved=True,
    )


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        sent_at=100,
        bid=100.0,
        ask=100.2,
        spread_points=20.0,
        point=0.01,
        atr_h1=10.0,
        atr_m15=2.0,
    )


def _kv(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def test_grade_risk_defaults_are_code_authoritative():
    assert SETTINGS.research_validation_initial_capital == 10000.0
    assert SETTINGS.research_risk_pct_a_plus == 1.00
    assert SETTINGS.research_risk_pct_a == 0.75
    assert SETTINGS.research_risk_pct_b_plus == 0.25


def test_bplus_plan_is_executable_but_exports_smallest_risk_tier():
    zone = _zone(Grade.B_PLUS)
    plan = _kv(active_plan_text(_analysis(zone)))
    assert plan["ea_mode"] == "DUAL_BRANCH"
    assert plan["grade"] == "B+"
    assert plan["risk_model"] == "GRADE_SCALED_INITIAL_CAPITAL_V1"
    assert plan["validation_initial_capital"] == "10000.00"
    assert plan["grade_risk_pct"] == "0.25"
    assert plan["bplus_reduced_risk"] == "1"


def test_execution_guard_preserves_bplus_authority_and_risk_truth():
    zone = _zone(Grade.B_PLUS)
    analysis = _analysis(zone)
    raw = active_plan_text(analysis)
    guarded = _kv(guard_plan_text(raw, analysis, _snapshot()))
    assert guarded["ea_mode"] == "DUAL_BRANCH"
    assert guarded["execution_authority"] == "HTF_CORE_HANDOFF"
    assert guarded["grade_risk_pct"] == "0.25"
    assert guarded["bplus_reduced_risk"] == "1"
