from types import SimpleNamespace

from app.models import Grade
from app.prompt_intraday_selection import prompt_intraday_rank


def _zone(low, high, touches, source_tf="H4>H1", grade=Grade.A_PLUS, ts=1):
    return SimpleNamespace(
        grade=grade,
        zone_low=low,
        zone_high=high,
        touch_count=touches,
        source_tf=source_tf,
        confluences=[],
        location_score=8.0,
        source_ts=ts,
    )


def test_nearer_valid_sell_outranks_remote_fresher_sell_for_today():
    snapshot = SimpleNamespace(mid=4297.25, atr_h1=20.995, xau_h1=[])
    nearer = _zone(4310.0, 4345.0, touches=1, ts=2)
    remote = _zone(4367.49, 4407.49, touches=0, ts=3)

    assert prompt_intraday_rank(nearer, snapshot) < prompt_intraday_rank(remote, snapshot)


def test_reachable_valid_watch_zone_precedes_remote_pristine_context_zone():
    snapshot = SimpleNamespace(mid=4297.25, atr_h1=20.995, xau_h1=[])
    nearby_b_plus = _zone(4300.0, 4330.0, touches=2, grade=Grade.B_PLUS, ts=4)
    remote_a_plus = _zone(4367.49, 4407.49, touches=0, grade=Grade.A_PLUS, ts=5)

    # Master Sniper battlefield selection is reachability-first once structural
    # validity is established. Grade/freshness controls execution authority; it
    # must not let a remote pristine source erase a nearer valid reaction area.
    assert prompt_intraday_rank(nearby_b_plus, snapshot) < prompt_intraday_rank(remote_a_plus, snapshot)
