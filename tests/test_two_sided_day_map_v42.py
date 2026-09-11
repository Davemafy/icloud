from app.engine import _dxy_implication_for_direction, _setup_type, _top_down_bias
from app.models import Bias, Direction, DxyImplication, Grade, Zone


def test_top_down_bias_uses_d1_h4_h1_together():
    assert _top_down_bias(Bias.BULLISH, Bias.BULLISH, Bias.BULLISH) == Bias.BULLISH
    assert _top_down_bias(Bias.BEARISH, Bias.BULLISH, Bias.BULLISH) == Bias.NEUTRAL
    assert _top_down_bias(Bias.NEUTRAL, Bias.BEARISH, Bias.BEARISH) == Bias.BEARISH


def test_setup_type_produces_continuation_and_reversal_sides():
    assert _setup_type(Direction.BUY_ONLY, Bias.BULLISH) == "CONTINUATION"
    assert _setup_type(Direction.SELL_ONLY, Bias.BULLISH) == "REVERSAL"
    assert _setup_type(Direction.SELL_ONLY, Bias.BEARISH) == "CONTINUATION"
    assert _setup_type(Direction.BUY_ONLY, Bias.BEARISH) == "REVERSAL"
    assert _setup_type(Direction.BUY_ONLY, Bias.NEUTRAL) == "TRANSITION_BUY"


def test_dxy_is_scored_per_zone_direction_not_only_overall_bias():
    # Bullish DXY supports an XAU SELL zone and conflicts with an XAU BUY zone.
    assert _dxy_implication_for_direction(Direction.SELL_ONLY, Bias.BULLISH, Bias.BULLISH, Bias.BULLISH) == DxyImplication.SUPPORTS
    assert _dxy_implication_for_direction(Direction.BUY_ONLY, Bias.BULLISH, Bias.BULLISH, Bias.BULLISH) == DxyImplication.CONFLICTS


def test_zone_schema_carries_two_sided_map_metadata():
    z = Zone(
        zone_id="Z", direction=Direction.BUY_ONLY, zone_low=100, zone_high=101, grade=Grade.A,
        source_tf="D1>H4>H1", setup_type="CONTINUATION", authority_stack=["D1", "H4", "H1"],
        requires_sweep="SSL", invalidation="x"
    )
    assert z.setup_type == "CONTINUATION"
    assert z.authority_stack == ["D1", "H4", "H1"]
