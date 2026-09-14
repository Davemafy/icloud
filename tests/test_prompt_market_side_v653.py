from app.models import Direction
from app import zone_runtime_policy as policy


def test_buy_zone_completely_above_current_price_is_rejected():
    code, reason = policy._market_side_rejection(Direction.BUY, 4300.0, 4340.0, 4280.0)
    assert code == "BUY_ZONE_ABOVE_CURRENT_PRICE"
    assert "below current price" in reason


def test_buy_zone_below_or_interacting_is_allowed():
    assert policy._market_side_rejection(Direction.BUY, 4200.0, 4250.0, 4280.0) == ("", "")
    assert policy._market_side_rejection(Direction.BUY, 4270.0, 4310.0, 4280.0) == ("", "")


def test_sell_zone_completely_below_current_price_is_rejected():
    code, reason = policy._market_side_rejection(Direction.SELL, 4200.0, 4250.0, 4280.0)
    assert code == "SELL_ZONE_BELOW_CURRENT_PRICE"
    assert "above current price" in reason


def test_sell_zone_above_or_interacting_is_allowed():
    assert policy._market_side_rejection(Direction.SELL, 4300.0, 4340.0, 4280.0) == ("", "")
    assert policy._market_side_rejection(Direction.SELL, 4270.0, 4310.0, 4280.0) == ("", "")
