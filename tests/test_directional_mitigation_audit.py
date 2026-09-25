from app.mitigation_audit import audit_directional_mitigations
from app.models import Bar, Direction


def _bar(ts, open_, high, low, close):
    return Bar(ts=ts, open=open_, high=high, low=low, close=close)


def test_wrong_side_sell_contact_is_logged_but_never_qualified():
    bars = [
        _bar(200, 104.0, 104.2, 103.6, 104.0),
        _bar(300, 103.5, 103.7, 100.4, 100.8),
        _bar(400, 100.8, 101.0, 99.7, 100.2),
        _bar(500, 99.0, 99.1, 97.2, 97.6),
    ]
    audit = audit_directional_mitigations(Direction.SELL, 100.0, 101.0, 98.0, 103.0, 200, bars)
    assert audit["qualified_mitigations"] == 0
    assert audit["counting_stopped"] is False
    wrong = [x for x in audit["events"] if x.get("reason") == "WRONG_APPROACH_SIDE"]
    assert len(wrong) == 1
    assert wrong[0]["approach_side"] == "ABOVE"


def test_sell_touch_is_not_qualified_until_later_clean_expected_side_departure():
    bars = [
        _bar(200, 97.5, 97.9, 97.1, 97.5),
        _bar(300, 99.0, 100.6, 98.8, 100.2),
        _bar(400, 100.2, 100.9, 99.8, 100.4),
    ]
    interim = audit_directional_mitigations(Direction.SELL, 100.0, 101.0, 98.0, 103.0, 200, bars)
    assert interim["qualified_mitigations"] == 0

    bars.append(_bar(500, 97.6, 97.8, 97.0, 97.4))
    completed = audit_directional_mitigations(Direction.SELL, 100.0, 101.0, 98.0, 103.0, 200, bars)
    assert completed["qualified_mitigations"] == 1
    event = next(x for x in completed["events"] if x.get("qualified"))
    assert event["armed_at"] == 200
    assert event["core_touched_at"] == 300
    assert event["qualified_at"] == 500
    assert event["approach_side"] == "BELOW"
    assert event["exit_side"] == "BELOW"


def test_same_bar_rejection_is_pending_and_cannot_consume_freshness():
    bars = [
        _bar(200, 97.5, 97.9, 97.1, 97.5),
        _bar(300, 99.0, 100.6, 97.2, 97.5),
    ]
    audit = audit_directional_mitigations(Direction.SELL, 100.0, 101.0, 98.0, 103.0, 200, bars)
    assert audit["qualified_mitigations"] == 0
    assert audit["raw_core_contact_episodes_before_invalidation"] == 1
    assert any(x.get("reason") == "REACTION_PENDING_CONFIRMATION" for x in audit["events"])


def test_buy_requires_above_core_then_later_clean_above_departure():
    bars = [
        _bar(200, 104.0, 104.2, 103.6, 104.0),
        _bar(300, 102.5, 103.0, 100.5, 100.8),
        _bar(400, 103.4, 103.7, 103.2, 103.5),
    ]
    audit = audit_directional_mitigations(Direction.BUY, 100.0, 101.0, 98.0, 103.0, 200, bars)
    assert audit["qualified_mitigations"] == 1
    event = next(x for x in audit["events"] if x.get("qualified"))
    assert event["approach_side"] == "ABOVE"
    assert event["core_touched_at"] == 300
    assert event["qualified_at"] == 400


def test_sell_accepted_invalidation_stops_original_zone_counting_forever():
    bars = [
        _bar(200, 97.5, 97.9, 97.1, 97.5),
        _bar(300, 99.0, 100.6, 98.8, 100.2),
        _bar(400, 103.2, 104.8, 103.1, 104.7),
        _bar(500, 97.5, 97.8, 97.0, 97.4),
        _bar(600, 99.0, 100.5, 98.8, 100.2),
        _bar(700, 97.5, 97.9, 97.0, 97.5),
    ]
    audit = audit_directional_mitigations(Direction.SELL, 100.0, 101.0, 98.0, 103.0, 200, bars)
    assert audit["qualified_mitigations"] == 0
    assert audit["counting_stopped"] is True
    assert audit["invalidated_at"] == 400
    assert audit["invalidation_reason"] == "M15_SINGLE_ACCEPTED_BODY"
    assert not any(x.get("core_touched_at") == 600 for x in audit["events"])


def test_unarmed_contact_does_not_consume_freshness():
    bars = [
        _bar(200, 99.5, 100.7, 99.0, 100.2),
        _bar(300, 99.0, 99.2, 97.0, 97.5),
    ]
    audit = audit_directional_mitigations(Direction.SELL, 100.0, 101.0, 98.0, 103.0, 200, bars)
    assert audit["qualified_mitigations"] == 0
    event = next(x for x in audit["events"] if x.get("event_type") == "INTERACTION")
    assert event["reason"] == "NO_EXPECTED_SIDE_ARM"


def test_history_coverage_is_explicit_and_never_assumed():
    bars = [
        _bar(500, 97.5, 97.9, 97.1, 97.5),
        _bar(600, 99.0, 100.6, 98.8, 100.2),
        _bar(700, 97.5, 97.9, 97.0, 97.4),
    ]
    audit = audit_directional_mitigations(Direction.SELL, 100.0, 101.0, 98.0, 103.0, 200, bars)
    assert audit["history_complete"] is False
    assert audit["history_start_ts"] == 500
    assert audit["history_required_from_ts"] == 200
    assert audit["history_gap_reason"] == "M15_HISTORY_STARTS_AFTER_SOURCE_READY"


def test_raw_contact_ledger_preserves_every_episode_inside_one_campaign():
    bars = [
        _bar(200, 104.0, 104.2, 103.6, 104.0),
        _bar(300, 101.4, 101.6, 100.5, 101.2),
        _bar(400, 101.8, 102.2, 101.4, 102.0),
        _bar(500, 101.3, 101.5, 100.4, 100.8),
        _bar(600, 101.7, 102.1, 101.4, 101.9),
        _bar(700, 101.2, 101.4, 100.2, 100.7),
        _bar(800, 103.2, 103.8, 103.1, 103.4),
    ]
    audit = audit_directional_mitigations(Direction.BUY, 100.0, 101.0, 98.0, 103.0, 200, bars)
    assert audit["raw_core_contact_episodes_before_invalidation"] == 3
    assert audit["qualified_mitigations"] == 1
    assert [x["core_touched_at"] for x in audit["raw_contacts"]] == [300, 500, 700]
    assert audit["raw_contacts"][0]["contact_role"] == "NEW_CORE_CONTACT_EPISODE"
    assert audit["raw_contacts"][1]["contact_role"] == "RECONTACT_WITHIN_OPEN_CAMPAIGN"
    assert audit["raw_contacts"][2]["contact_role"] == "RECONTACT_WITHIN_OPEN_CAMPAIGN"
    assert all(x["approach_side"] == "ABOVE" for x in audit["raw_contacts"])
    assert all(x["counts_freshness_by_itself"] is False for x in audit["raw_contacts"])


def test_raw_recontact_reports_immediate_side_separately_from_campaign_origin():
    bars = [
        _bar(200, 104.0, 104.2, 103.6, 104.0),
        _bar(300, 101.4, 101.6, 100.5, 101.2),
        _bar(400, 99.3, 99.7, 98.8, 99.5),
        _bar(500, 99.6, 100.5, 99.4, 100.2),
        _bar(600, 103.2, 103.8, 103.1, 103.5),
    ]
    audit = audit_directional_mitigations(Direction.BUY, 100.0, 101.0, 98.0, 103.0, 200, bars)
    contacts = audit["raw_contacts"]
    assert len(contacts) == 2
    assert contacts[0]["campaign_approach_side"] == "ABOVE"
    assert contacts[0]["immediate_approach_side"] == "ABOVE_CORE"
    assert contacts[1]["campaign_approach_side"] == "ABOVE"
    assert contacts[1]["immediate_approach_side"] == "BELOW_CORE"
    assert contacts[1]["immediate_approach_ts"] == 400
    assert audit["qualified_mitigations"] == 1
