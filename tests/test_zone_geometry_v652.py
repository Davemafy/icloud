from app import institutional_two_zone as zoning
from app import zone_runtime_policy as policy


def test_master_sniper_geometry_contract_disables_synthetic_widths():
    policy.install_zone_geometry_policy()

    assert policy.XAU_POINTS_PER_PIP == 10.0
    assert policy.MIN_SWEEP_ROOM_POINTS == 0.0
    assert policy.MIN_SWEEP_ROOM_PIPS == 0.0
    assert policy.PROMPT_ZONE_CONTRACT == "MASTER_SNIPER_SOURCE_EXACT_V6577"

    zero = {"core_min": 0.0, "core_max": 0.0, "envelope_min": 0.0, "envelope_max": 0.0}
    assert policy._geometry_pips("H1") == zero
    assert policy._geometry_pips("H4") == zero
    assert policy._geometry_pips("H4>H1") == zero

    # The installed base-engine seams must not manufacture minimum core,
    # envelope or distal sweep-room widths.
    assert policy.CORE_MIN_POINTS == 0.0
    assert policy.CORE_MAX_POINTS == 0.0
    assert policy.ENVELOPE_MIN_POINTS == 0.0
    assert policy.ENVELOPE_MAX_POINTS == 0.0
