from app.engine import active_plan_text, build_candidate_analysis
from app.models import Direction, Grade, Zone
from tests.helpers import make_snapshot


def test_candidate_zones_are_xau_only():
    a = build_candidate_analysis(make_snapshot())
    assert all(("XAU" in z.instrument.upper() or "GOLD" in z.instrument.upper()) for z in a.zones)


def test_plan_does_not_serialize_non_xau_view_zone():
    a = build_candidate_analysis(make_snapshot())
    a.approved = True
    a.zones.append(Zone(
        instrument="DXYUSD", zone_id="DXY_TEST", direction=Direction.SELL_ONLY,
        zone_low=98.9, zone_high=99.1, grade=Grade.A, source_tf="DXY:H4",
        requires_sweep="BSL", invalidation="context only"
    ))
    text = active_plan_text(a)
    assert "DXY_TEST" not in text
    assert "instrument=DXYUSD" not in text
