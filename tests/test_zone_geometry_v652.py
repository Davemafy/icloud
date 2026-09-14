from app import institutional_two_zone as zoning
from app import zone_runtime_policy as policy


def test_v652_geometry_contract_installs_requested_pip_widths():
    policy.install_zone_geometry_policy()

    assert policy.XAU_POINTS_PER_PIP == 10.0
    assert zoning.CORE_MIN_POINTS == 1000.0
    assert zoning.CORE_MAX_POINTS == 2000.0
    assert zoning.ENVELOPE_MIN_POINTS == 3000.0
    assert zoning.ENVELOPE_MAX_POINTS == 4000.0
    assert zoning.MIN_SWEEP_ROOM_POINTS == 500.0

    assert policy.CORE_MIN_PIPS == 100.0
    assert policy.CORE_MAX_PIPS == 200.0
    assert policy.ENVELOPE_MIN_PIPS == 300.0
    assert policy.ENVELOPE_MAX_PIPS == 400.0
    assert policy.MIN_SWEEP_ROOM_PIPS == 50.0
