from datetime import datetime, timezone

from app.config import SETTINGS
from app.engine import active_plan_text
from app.execution_safety import guard_plan_text
from app.models import Analysis, Direction, Grade, MarketSnapshot, Zone, ZoneState
from app import plan_execution_guard
from app.professional_zone_execution_separation import apply_execution_separation
from app.risk_matrix import RISK_MODEL, execution_grade_eligible, flip_risk_pct, original_risk_pct, zone_risk_context


def _zone(grade: Grade, *, countertrend: bool = False, touches: int | None = None) -> Zone:
    if touches is None:
        touches = 0 if grade == Grade.A_PLUS else 1
    return Zone(
        zone_id=f"{grade.value}_{'CT' if countertrend else 'TR'}",
        original_direction=Direction.BUY if not countertrend else Direction.SELL,
        flip_direction=Direction.SELL if not countertrend else Direction.BUY,
        setup_type="REVERSAL" if countertrend else "CONTINUATION",
        source_tf="H4>H1", grade=grade, state=ZoneState.ACTIVE,
        core_low=99.0, core_high=101.0, core_method="M1_READY|PROMPT_SWEEP_ROOM_GEOMETRY",
        location_score=8.0, zone_low=95.0, zone_high=105.0, touch_count=touches,
        independent_confluence_count=4,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "SSL_IN_MARKED_ZONE" if not countertrend else "BSL_IN_MARKED_ZONE"],
        source_ts=10, invalidation_level=95.0, invalidation_rule="M15 accepted invalidation",
        original_target1=110.0 if not countertrend else 90.0,
        original_target2=115.0 if not countertrend else 85.0,
        original_target3=120.0 if not countertrend else 80.0,
        flip_target1=90.0 if not countertrend else 110.0,
        flip_target2=85.0 if not countertrend else 115.0,
        clear_run=9.0, countertrend=countertrend,
    )


def _analysis(zone: Zone) -> Analysis:
    return Analysis(analysis_id="A_RISK", generated_at=100, snapshot_at=100,
                    overall_bias=Direction.BUY, zones=[zone], selected_zone_id=zone.zone_id,
                    approved=True, ai_approved=True)


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(sent_at=int(datetime.now(timezone.utc).timestamp()), bid=100.0, ask=100.2,
                          spread_points=20.0, point=0.01, atr_h1=10.0, atr_m15=2.0)


def _kv(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def test_context_grade_risk_defaults_are_code_authoritative():
    assert SETTINGS.research_validation_initial_capital == 10000.0
    assert SETTINGS.research_risk_pct_trend_a_plus == 1.00
    assert SETTINGS.research_risk_pct_trend_a == 0.75
    assert SETTINGS.research_risk_pct_countertrend_a_plus == 0.50
    assert SETTINGS.research_risk_pct_countertrend_a == 0.25
    assert SETTINGS.research_risk_pct_b_plus == 0.25
    assert SETTINGS.research_risk_epoch == "MASTER_SNIPER_CONTEXT_GRADE_10000_V5_BPLUS_EXEC"


def test_context_x_grade_matrix_exact_percentages():
    cases = [
        (_zone(Grade.A_PLUS, countertrend=False), "TREND", 1.00, 0.50),
        (_zone(Grade.A, countertrend=False), "TREND", 0.75, 0.25),
        (_zone(Grade.A_PLUS, countertrend=True), "COUNTERTREND", 0.50, 1.00),
        (_zone(Grade.A, countertrend=True), "COUNTERTREND", 0.25, 0.75),
        (_zone(Grade.B_PLUS, countertrend=False), "TREND", 0.25, 0.25),
        (_zone(Grade.B_PLUS, countertrend=True), "COUNTERTREND", 0.25, 0.25),
    ]
    for zone, context, original, flip in cases:
        assert zone_risk_context(zone) == context
        assert original_risk_pct(zone) == original
        assert flip_risk_pct(zone) == flip
        assert execution_grade_eligible(zone)


def test_second_touch_a_remains_eligible_but_a_plus_and_bplus_do_not():
    assert execution_grade_eligible(_zone(Grade.A, touches=2))
    assert not execution_grade_eligible(_zone(Grade.A_PLUS, touches=2))
    assert not execution_grade_eligible(_zone(Grade.B_PLUS, touches=2))


def test_bplus_has_first_qualified_mitigation_reduced_risk_authority():
    zone = _zone(Grade.B_PLUS, touches=1)
    analysis = _analysis(zone)
    plan = _kv(active_plan_text(analysis))
    assert analysis.ai_approved is True
    assert execution_grade_eligible(zone)
    # No snapshot means the final professional execution layer must fail closed;
    # the B+ grade/risk authority itself remains intact in the exported plan.
    assert plan["ea_mode"] == "WATCH_ONLY"
    assert plan["grade"] == "B+"
    assert plan["risk_model"] == RISK_MODEL
    assert plan["grade_risk_pct"] == "0.25"
    assert plan["original_risk_pct"] == "0.25"
    assert plan["flip_risk_pct"] == "0.25"
    assert plan["bplus_execution_authority"] == "1"
    assert "SNAPSHOT" in plan["separation_guard"]


def test_bplus_second_qualified_mitigation_is_watch_only():
    zone = _zone(Grade.B_PLUS, touches=2)
    plan = _kv(active_plan_text(_analysis(zone)))
    assert plan["ea_mode"] == "WATCH_ONLY"
    assert plan["bplus_execution_authority"] == "0"


def test_guard_exports_countertrend_a_quarter_percent_base_risk(monkeypatch):
    zone = _zone(Grade.A, countertrend=True)
    analysis = _analysis(zone)
    snap = _snapshot()
    # Isolate the history-window dimension only. The production execution guard
    # remains fail-closed for every other authority requirement; this regression
    # verifies that a safety hold never corrupts the context x grade risk contract.
    monkeypatch.setattr("app.professional_zone_execution_separation.history_audit", lambda _snapshot: (True, []))
    raw = plan_execution_guard._original_active_plan_text(analysis, snap)
    guarded = _kv(apply_execution_separation(guard_plan_text(raw, analysis, snap), analysis, snap))
    assert guarded["ea_mode"] == "WATCH_ONLY"
    assert guarded["execution_authority"] == "NONE"
    assert guarded["risk_model"] == RISK_MODEL
    assert guarded["risk_context"] == "COUNTERTREND"
    assert guarded["grade_risk_pct"] == "0.25"
    assert guarded["original_risk_pct"] == "0.25"
    assert guarded["flip_risk_pct"] == "0.75"
