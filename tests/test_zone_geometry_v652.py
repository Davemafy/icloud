from app import institutional_two_zone as zoning
from app import zone_runtime_policy as policy


def test_v659_geometry_contract_installs_professional_source_tf_widths():
    policy.install_zone_geometry_policy()

    assert policy.XAU_POINTS_PER_PIP == 10.0
    assert zoning.MIN_SWEEP_ROOM_POINTS == 500.0
    assert policy.MIN_SWEEP_ROOM_PIPS == 50.0

    assert policy._geometry_pips("H1") == {
        "core_min": 60.0,
        "core_max": 100.0,
        "envelope_min": 140.0,
        "envelope_max": 220.0,
    }
    assert policy._geometry_pips("H4") == {
        "core_min": 80.0,
        "core_max": 140.0,
        "envelope_min": 180.0,
        "envelope_max": 260.0,
    }
    assert policy._geometry_pips("H4>H1") == {
        "core_min": 60.0,
        "core_max": 100.0,
        "envelope_min": 180.0,
        "envelope_max": 260.0,
    }

    # Compatibility globals expose the broadest installed range only; actual
    # qualification is source-TF-specific through the installed functions.
    assert zoning.CORE_MIN_POINTS == 600.0
    assert zoning.CORE_MAX_POINTS == 1400.0
    assert zoning.ENVELOPE_MIN_POINTS == 1400.0
    assert zoning.ENVELOPE_MAX_POINTS == 2600.0
