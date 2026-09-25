from app.mitigation_audit import audit_directional_mitigations
from app.models import Bar, Direction


def _bar(ts, open_, high, low, close):
    return Bar(ts=ts, open=open_, high=high, low=low, close=close)


def test_same_bar_sell_rejection_is_pending_not_freshness_consuming():
    bars = [
        _bar(200, 97.5, 97.9, 97.1, 97.5),
        # Correct-side approach, core touch, and close below envelope on same bar.
        _bar(300, 99.0, 100.6, 97.2, 97.5),
    ]
    audit = audit_directional_mitigations(
        Direction.SELL, 100.0, 101.0, 98.0, 103.0, 200, bars
    )
    assert audit["qualified_mitigations"] == 0
    assert audit["raw_core_contact_episodes_before_invalidation"] == 1
    assert any(x.get("reason") == "REACTION_PENDING_CONFIRMATION" for x in audit["events"])


def test_later_clean_sell_departure_confirms_exactly_one_mitigation():
    bars = [
        _bar(200, 97.5, 97.9, 97.1, 97.5),
        _bar(300, 99.0, 100.6, 97.2, 97.5),
        # Recontact remains the same campaign and cannot qualify it.
        _bar(400, 98.1, 100.4, 97.4, 97.6),
        # Subsequent bar is below the envelope and its range is clear of core.
        _bar(500, 97.4, 97.8, 96.8, 97.1),
    ]
    audit = audit_directional_mitigations(
        Direction.SELL, 100.0, 101.0, 98.0, 103.0, 200, bars
    )
    assert audit["qualified_mitigations"] == 1
    assert audit["raw_core_contact_episodes_before_invalidation"] == 1
    event = next(x for x in audit["events"] if x.get("qualified"))
    assert event["core_touched_at"] == 300
    assert event["qualified_at"] == 500
    assert event["reason"] == "CONFIRMED_DIRECTIONAL_CORE_REACTION_COMPLETE"


def test_same_bar_buy_rejection_also_requires_later_clean_departure():
    bars = [
        _bar(200, 104.0, 104.2, 103.6, 104.0),
        _bar(300, 102.5, 103.4, 100.5, 103.3),
    ]
    interim = audit_directional_mitigations(
        Direction.BUY, 100.0, 101.0, 98.0, 103.0, 200, bars
    )
    assert interim["qualified_mitigations"] == 0

    bars.append(_bar(400, 103.4, 104.0, 103.2, 103.8))
    completed = audit_directional_mitigations(
        Direction.BUY, 100.0, 101.0, 98.0, 103.0, 200, bars
    )
    assert completed["qualified_mitigations"] == 1
    event = next(x for x in completed["events"] if x.get("qualified"))
    assert event["qualified_at"] == 400
