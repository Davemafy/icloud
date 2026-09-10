from app.ai import _user_payload
from app.config import SETTINGS
from app.engine import _intraday_zone_grade, build_candidate_analysis
from app.models import Bias, Direction, DxyImplication, Grade
from tests.helpers import make_snapshot


def test_intraday_profile_defaults_and_no_swing_zone_sources():
    assert SETTINGS.trading_profile == "INTRADAY_SCALP"
    analysis = build_candidate_analysis(make_snapshot())
    assert all(z.source_tf not in {"D1", "H4"} for z in analysis.zones)
    assert "D1/H4 are context only" in analysis.trader_brief


def test_fresh_supported_m15_reversal_can_be_a_but_dxy_conflict_downgrades():
    grade = _intraday_zone_grade(
        Direction.SELL_ONLY,
        h1_bias=Bias.BULLISH,
        m15_bias=Bias.BEARISH,
        overall=Bias.NEUTRAL,
        implication=DxyImplication.SUPPORTS,
        touches=0,
        nested_h1=False,
    )
    assert grade == Grade.A

    conflicted = _intraday_zone_grade(
        Direction.SELL_ONLY,
        h1_bias=Bias.BULLISH,
        m15_bias=Bias.BEARISH,
        overall=Bias.NEUTRAL,
        implication=DxyImplication.CONFLICTS,
        touches=0,
        nested_h1=False,
    )
    assert conflicted == Grade.B_PLUS


def test_ai_prompt_is_explicitly_intraday_scalp():
    snap = make_snapshot()
    base = build_candidate_analysis(snap)
    instruction = _user_payload(snap, base)["instruction"]
    assert "TRADING PROFILE IS INTRADAY_SCALP" in instruction
    assert "not distant swing-entry zones" in instruction
