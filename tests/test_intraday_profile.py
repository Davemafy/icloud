from app.ai import _user_payload
from app.config import SETTINGS
from app.engine import _primary_zone_grade, active_plan_text, build_candidate_analysis
from app.models import Bias, Direction, DxyImplication, Grade
from tests.helpers import make_snapshot


def test_v42_profile_uses_d1_h4_h1_as_zone_authority():
    assert SETTINGS.trading_profile == "INTRADAY_HTF_ZONE_M1"
    analysis = build_candidate_analysis(make_snapshot())
    assert all(z.source_tf in {"D1>H4>H1", "D1>H4", "H4>H1", "D1>H1", "H1", "H4"} for z in analysis.zones)
    assert all("M15" not in z.source_tf for z in analysis.zones)
    assert "D1/H4/H1 jointly form the institutional zone map" in analysis.trader_brief
    assert "M15 is consumed only while qualifying each zone" in analysis.trader_brief


def test_h4_h1_pair_with_m15_qualification_can_be_a_plus():
    grade = _primary_zone_grade(
        Direction.SELL_ONLY,
        d1_bias=Bias.BEARISH,
        h4_bias=Bias.BEARISH,
        h1_bias=Bias.BEARISH,
        overall=Bias.BEARISH,
        zone_implication=DxyImplication.SUPPORTS,
        touches=0,
        authority_stack=["D1", "H4", "H1"],
        m15_confirmation_score=3,
    )
    assert grade == Grade.A_PLUS


def test_m15_qualification_does_not_override_htf_zone_authority():
    # Even strong M15 evidence cannot manufacture an A/A+ zone when H4/H1 do not
    # authorize the location/direction. M15 is a qualifier, not the zone source.
    grade = _primary_zone_grade(
        Direction.SELL_ONLY,
        d1_bias=Bias.BULLISH,
        h4_bias=Bias.BULLISH,
        h1_bias=Bias.BULLISH,
        overall=Bias.BULLISH,
        zone_implication=DxyImplication.SUPPORTS,
        touches=0,
        authority_stack=["H1"],
        m15_confirmation_score=3,
    )
    assert grade == Grade.B_PLUS


def test_ai_prompt_explicitly_ends_m15_role_at_zone_publication():
    snap = make_snapshot()
    base = build_candidate_analysis(snap)
    instruction = _user_payload(snap, base)["instruction"]
    assert "D1/H4/H1 TOP-DOWN ZONE MAP" in instruction
    assert "M15 usage ENDS when the cloud publishes the zone" in instruction
    assert "do NOT require a later M15" in instruction
    assert "M1 alone may validate execution" in instruction


def test_mt5_plan_has_no_m15_execution_gate():
    analysis = build_candidate_analysis(make_snapshot())
    analysis.approved = True
    plan = active_plan_text(analysis)
    assert "requires_m15" not in plan.lower()
    assert "m15_confirmation_required" not in plan.lower()
    # ATR M15 remains informational/risk context and is allowed in the plan.
    assert "atr_m15=" in plan
