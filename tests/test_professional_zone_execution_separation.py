from types import SimpleNamespace

from app.models import Direction, Grade
from app.professional_zone_execution_separation import (
    conservative_runway,
    history_audit,
    zone_layer,
)


def _bars(start, end, step):
    return [SimpleNamespace(ts=t) for t in range(start, end + 1, step)]


def _snapshot(full=True, dxy_h4_full=True):
    day = 86400
    end = 400 * day
    return SimpleNamespace(
        xau_d1=_bars(0, end, day) if full else _bars(390 * day, end, day),
        xau_h4=_bars(0, end, 4 * 3600),
        xau_h1=_bars(0, end, 3600),
        xau_m15=_bars(390 * day, end, 900),
        dxy_d1=_bars(0, end, day),
        dxy_h4=_bars(0, end, 4 * 3600) if dxy_h4_full else _bars(390 * day, end, 4 * 3600),
        dxy_h1=_bars(0, end, 3600),
    )


def _zone(grade=Grade.A, touches=0, direction=Direction.BUY, countertrend=False, target=110.0):
    return SimpleNamespace(
        grade=grade,
        touch_count=touches,
        original_direction=direction,
        core_low=100.0,
        core_high=101.0,
        original_target1=target,
        countertrend=countertrend,
    )


def test_required_analysis_windows_pass_with_sufficient_history():
    ok, failures = history_audit(_snapshot(True))
    assert ok
    assert failures == []


def test_incomplete_d1_history_fails_closed_without_deleting_map_context():
    ok, failures = history_audit(_snapshot(False))
    assert not ok
    assert "XAU_D1_1Y" in failures
    assert zone_layer(_zone(), ok, True) == "MAP_CONTEXT"


def test_incomplete_dxy_h4_history_fails_closed_without_deleting_map_context():
    ok, failures = history_audit(_snapshot(True, dxy_h4_full=False))
    assert not ok
    assert "DXY_H4_4M" in failures
    assert zone_layer(_zone(), ok, True) == "MAP_CONTEXT"


def test_conservative_runway_uses_tactical_core_edge_not_zone_midpoint():
    runway, required, ok = conservative_runway(_zone(direction=Direction.BUY, target=110.0))
    assert runway == 9.0
    assert required > 0
    assert ok == (runway >= required)


def test_exhausted_bplus_remains_map_context_but_fresh_bplus_is_candidate():
    assert zone_layer(_zone(Grade.B_PLUS, touches=1), True, True) == "EXECUTION_CANDIDATE"
    assert zone_layer(_zone(Grade.B_PLUS, touches=2), True, True) == "MAP_CONTEXT"


def test_runway_failure_does_not_reject_or_move_zone_it_only_removes_execution_layer():
    z = _zone(Grade.A_PLUS, touches=0)
    assert zone_layer(z, True, False) == "MAP_CONTEXT"