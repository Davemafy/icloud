from types import SimpleNamespace

from app.master_sniper_zone_authority import install_master_sniper_zone_authority
from app.models import Direction, Grade, ZoneState
from app import institutional_two_zone as engine


def _zone(zone_id, direction, low, high):
    return SimpleNamespace(
        zone_id=zone_id,
        original_direction=direction,
        zone_low=low,
        zone_high=high,
        core_low=low,
        core_high=high,
        source_tf="H1",
        grade=Grade.A,
        state=ZoneState.ACTIVE,
        touch_count=0,
        confluences=["LIQUIDITY_IN_MARKED_ZONE", "INSTITUTIONAL_DISPLACEMENT"],
        location_score=8.0,
        source_ts=1,
    )


def test_master_sniper_rank_penalizes_wrong_side_buy():
    install_master_sniper_zone_authority()
    snap = SimpleNamespace(mid=4250.0, bid=4249.9, ask=4250.1)
    valid = _zone("BUY_BELOW", Direction.BUY, 4230.0, 4240.0)
    wrong = _zone("BUY_ABOVE", Direction.BUY, 4260.0, 4270.0)
    assert engine._rank(valid, snap) < engine._rank(wrong, snap)


def test_master_sniper_rank_penalizes_wrong_side_sell():
    install_master_sniper_zone_authority()
    snap = SimpleNamespace(mid=4250.0, bid=4249.9, ask=4250.1)
    valid = _zone("SELL_ABOVE", Direction.SELL, 4260.0, 4270.0)
    wrong = _zone("SELL_BELOW", Direction.SELL, 4230.0, 4240.0)
    assert engine._rank(valid, snap) < engine._rank(wrong, snap)


def test_interacting_zone_is_not_rejected_by_side_rule():
    install_master_sniper_zone_authority()
    snap = SimpleNamespace(mid=4250.0, bid=4249.9, ask=4250.1)
    buy = _zone("BUY_INTERACT", Direction.BUY, 4245.0, 4255.0)
    sell = _zone("SELL_INTERACT", Direction.SELL, 4245.0, 4255.0)
    # Interaction is intentionally neutral in the first rank fields for both
    # directions: once price is inside the zone, it is a legitimate live test.
    assert engine._rank(buy, snap)[0:2] == (0, 0)
    assert engine._rank(sell, snap)[0:2] == (0, 0)
