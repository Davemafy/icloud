from types import SimpleNamespace

from app.models import Direction, Grade
from app.professional_zone_execution_separation import (
    apply_execution_separation,
    confluence_history_audit,
    conservative_runway,
    entry_specific_runway_candidate,
    history_audit,
    history_metrics,
    zone_layer,
)


def _bars(start, end, step):
    return [SimpleNamespace(ts=t) for t in range(start, end + 1, step)]


def _snapshot(full=True, dxy_h4_extended=True, dxy_h4_minimum=True):
    day = 86400
    end = 400 * day
    if dxy_h4_extended:
        dxy_h4 = _bars(0, end, 4 * 3600)
    elif dxy_h4_minimum:
        # Plenty of bars for prompt confirmation, but less than four months of
        # extended DXY context. This is a warning only.
        dxy_h4 = _bars(350 * day, end, 4 * 3600)
    else:
        # Fewer than the live prompt minimum 80 H4 bars: hard fail.
        dxy_h4 = _bars(395 * day, end, 4 * 3600)
    return SimpleNamespace(
        xau_d1=_bars(0, end, day) if full else _bars(390 * day, end, day),
        xau_h4=_bars(0, end, 4 * 3600),
        xau_h1=_bars(0, end, 3600),
        xau_m15=_bars(390 * day, end, 900),
        dxy_d1=_bars(0, end, day),
        dxy_h4=dxy_h4,
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
        setup_type="REVERSAL" if countertrend else "CONTINUATION",
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


def test_short_extended_dxy_h4_is_confluence_warning_not_xau_authority_veto():
    snapshot = _snapshot(True, dxy_h4_extended=False, dxy_h4_minimum=True)
    ok, failures = history_audit(snapshot)
    assert ok
    assert failures == []
    assert "DXY_H4_EXTENDED_LT_4M" in confluence_history_audit(snapshot)
    assert zone_layer(_zone(), ok, True) == "EXECUTION_CANDIDATE"


def test_dxy_h4_below_prompt_minimum_still_fails_closed():
    snapshot = _snapshot(True, dxy_h4_extended=False, dxy_h4_minimum=False)
    ok, failures = history_audit(snapshot)
    assert not ok
    assert "DXY_H4_MIN_BARS" in failures
    assert zone_layer(_zone(), ok, True) == "MAP_CONTEXT"


def test_conservative_runway_uses_tactical_core_edge_not_zone_midpoint():
    runway, required, ok = conservative_runway(_zone(direction=Direction.BUY, target=110.0))
    assert runway == 9.0
    assert required > 0
    assert ok == (runway >= required)


def test_entry_specific_buy_runway_keeps_only_the_viable_core_subwindow():
    zone = _zone(direction=Direction.BUY, target=110.0)
    zone.core_high = 106.0
    conservative, required, old_ok = conservative_runway(zone)
    runway, required2, ok, entry_limit, low, high = entry_specific_runway_candidate(zone)
    assert conservative == 4.0
    assert required == 5.0
    assert old_ok is False
    assert runway == 10.0
    assert required2 == 5.0
    assert ok is True
    assert entry_limit == 105.0
    assert (low, high) == (100.0, 105.0)


def test_entry_specific_sell_runway_keeps_only_the_viable_core_subwindow():
    zone = _zone(direction=Direction.SELL, target=96.0)
    zone.core_high = 106.0
    conservative, required, old_ok = conservative_runway(zone)
    runway, required2, ok, entry_limit, low, high = entry_specific_runway_candidate(zone)
    assert conservative == 4.0
    assert required == 5.0
    assert old_ok is False
    assert runway == 10.0
    assert required2 == 5.0
    assert ok is True
    assert entry_limit == 101.0
    assert (low, high) == (101.0, 106.0)


def test_entry_specific_runway_still_fails_when_no_core_price_can_meet_minimum():
    zone = _zone(direction=Direction.BUY, target=104.0)
    zone.core_high = 106.0
    runway, required, ok, entry_limit, low, high = entry_specific_runway_candidate(zone)
    assert runway == 4.0
    assert required == 5.0
    assert ok is False
    assert entry_limit == 99.0
    assert low == 0.0 and high == 0.0


def test_bplus_touch_count_is_telemetry_only_for_execution_layer():
    assert zone_layer(_zone(Grade.B_PLUS, touches=1), True, True) == "EXECUTION_CANDIDATE"
    assert zone_layer(_zone(Grade.B_PLUS, touches=20), True, True) == "EXECUTION_CANDIDATE"


def test_runway_failure_does_not_reject_or_move_zone_it_only_removes_execution_layer():
    z = _zone(Grade.A_PLUS, touches=0)
    assert zone_layer(z, True, False) == "MAP_CONTEXT"

def test_conservative_runway_can_use_next_open_owner_objective():
    zone = _zone(direction=Direction.BUY, countertrend=True, target=110.0)
    runway, required, ok = conservative_runway(zone, target_override=130.0)
    assert runway == 29.0
    assert required == 10.0
    assert ok is True


def test_final_separation_uses_next_open_target_not_behind_activation_tp1(monkeypatch):
    zone = SimpleNamespace(
        zone_id="PZ_H4H1_BUY_6",
        grade=Grade.A_PLUS,
        touch_count=0,
        original_direction=Direction.BUY,
        core_low=4254.41,
        core_high=4275.79,
        original_target1=4285.0,
        countertrend=True,
        setup_type="REVERSAL",
    )
    analysis = SimpleNamespace(zones=[zone], generated_at=1000)
    snapshot = SimpleNamespace(
        spread_points=19.0,
        sent_at=1000,
        kind="HISTORICAL_REPLAY",
    )
    monkeypatch.setattr(
        "app.professional_zone_execution_separation.history_audit",
        lambda _snapshot: (True, []),
    )
    raw = (
        "ea_mode=DUAL_BRANCH\n"
        "zone_id=PZ_H4H1_BUY_6\n"
        "execution_authority=HTF_CORE_HANDOFF\n"
        "next_open_target=4303.32000\n"
        "original_target1=4285.00000\n"
    )
    out = dict(
        line.split("=", 1)
        for line in apply_execution_separation(raw, analysis, snapshot).splitlines()
        if "=" in line
    )
    assert out["ea_mode"] == "DUAL_BRANCH"
    assert out["execution_authority"] == "HTF_CORE_HANDOFF"
    assert out["usable_runway_target"] == "4303.32000"
    assert out["usable_runway_target_basis"] == "FINAL_PLAN_NEXT_OPEN_TARGET"
    assert abs(float(out["usable_runway"]) - 27.53) < 1e-9
    assert out["required_runway"] == "10.00000"
    assert out["usable_runway_ok"] == "1"
    assert out["separation_guard"] == "PASS"


def test_history_span_is_order_independent():
    snapshot = _snapshot(True)
    snapshot.xau_d1 = list(reversed(snapshot.xau_d1))
    snapshot.xau_h4 = list(reversed(snapshot.xau_h4))
    snapshot.xau_h1 = list(reversed(snapshot.xau_h1))
    ok, failures = history_audit(snapshot)
    assert ok
    assert failures == []


def test_history_metrics_expose_bar_counts_and_depth():
    metrics = history_metrics(_snapshot(True))
    assert metrics["XAU_D1_bars"] > 80
    assert metrics["XAU_D1_span_days"] >= 350
    assert metrics["XAU_M15_trading_days"] >= 3
    assert metrics["DXY_H4_bars"] >= 80


def test_final_plan_exports_exact_history_failures_warnings_and_metrics(monkeypatch):
    zone = SimpleNamespace(
        zone_id="Z1",
        grade=Grade.A_PLUS,
        touch_count=0,
        original_direction=Direction.BUY,
        core_low=100.0,
        core_high=101.0,
        original_target1=120.0,
        countertrend=False,
        setup_type="CONTINUATION",
    )
    analysis = SimpleNamespace(zones=[zone], generated_at=400 * 86400)
    snapshot = _snapshot(True, dxy_h4_extended=False, dxy_h4_minimum=True)
    snapshot.spread_points = 10.0
    snapshot.sent_at = analysis.generated_at
    snapshot.kind = "HISTORICAL_REPLAY"
    raw = (
        "ea_mode=DUAL_BRANCH\n"
        "zone_id=Z1\n"
        "execution_authority=HTF_CORE_HANDOFF\n"
        "next_open_target=120.0\n"
    )
    out = dict(
        line.split("=", 1)
        for line in apply_execution_separation(raw, analysis, snapshot).splitlines()
        if "=" in line
    )
    assert out["history_window_ok"] == "1"
    assert out["history_window_failures"] == "NONE"
    assert "DXY_H4_EXTENDED_LT_4M" in out["history_confluence_warnings"]
    assert "XAU_D1:" in out["history_window_metrics"]
    assert "DXY_H4:" in out["history_window_metrics"]
    assert out["ea_mode"] == "DUAL_BRANCH"


def test_final_separation_uses_entry_specific_runway_for_matching_runtime(monkeypatch):
    zone = SimpleNamespace(
        zone_id="Z_ENTRY_RUNWAY",
        grade=Grade.A,
        touch_count=0,
        original_direction=Direction.BUY,
        core_low=100.0,
        core_high=106.0,
        original_target1=110.0,
        countertrend=False,
        setup_type="CONTINUATION",
    )
    analysis = SimpleNamespace(zones=[zone], generated_at=1000)
    snapshot = SimpleNamespace(
        spread_points=10.0,
        sent_at=1000,
        kind="HISTORICAL_REPLAY",
    )
    monkeypatch.setattr(
        "app.professional_zone_execution_separation.history_audit",
        lambda _snapshot: (True, []),
    )
    monkeypatch.setattr(
        "app.professional_zone_execution_separation._entry_specific_runway_runtime_ready",
        lambda _snapshot: True,
    )
    raw = (
        "ea_mode=DUAL_BRANCH\n"
        "zone_id=Z_ENTRY_RUNWAY\n"
        "execution_authority=HTF_CORE_HANDOFF\n"
        "next_open_target=110.0\n"
    )
    out = dict(
        line.split("=", 1)
        for line in apply_execution_separation(raw, analysis, snapshot).splitlines()
        if "=" in line
    )
    assert out["runway_gate_mode"] == "ENTRY_SPECIFIC_M1_ORDER"
    assert out["entry_specific_runway_runtime_ready"] == "1"
    assert out["conservative_edge_runway"] == "4.00000"
    assert out["usable_runway"] == "10.00000"
    assert out["required_runway"] == "5.00000"
    assert out["usable_runway_ok"] == "1"
    assert out["runway_entry_limit"] == "105.00000"
    assert out["runway_candidate_low"] == "100.00000"
    assert out["runway_candidate_high"] == "105.00000"
    assert out["separation_guard"] == "PASS"


def test_live_rollout_keeps_conservative_guard_until_sequence_348_is_confirmed(monkeypatch):
    zone = SimpleNamespace(
        zone_id="Z_COMPAT",
        grade=Grade.A,
        touch_count=0,
        original_direction=Direction.BUY,
        core_low=100.0,
        core_high=106.0,
        original_target1=110.0,
        countertrend=False,
        setup_type="CONTINUATION",
    )
    analysis = SimpleNamespace(zones=[zone], generated_at=1000)
    snapshot = SimpleNamespace(
        spread_points=10.0,
        sent_at=1000,
        kind="LIVE",
    )
    monkeypatch.setattr(
        "app.professional_zone_execution_separation.history_audit",
        lambda _snapshot: (True, []),
    )
    monkeypatch.setattr(
        "app.professional_zone_execution_separation._entry_specific_runway_runtime_ready",
        lambda _snapshot: False,
    )
    raw = (
        "ea_mode=DUAL_BRANCH\n"
        "zone_id=Z_COMPAT\n"
        "execution_authority=HTF_CORE_HANDOFF\n"
        "next_open_target=110.0\n"
    )
    # Live clock age is not part of this runway test; pin the snapshot safety
    # result so only the structural runway mode is under examination.
    snapshot.sent_at = int(__import__("time").time())
    analysis.generated_at = snapshot.sent_at
    out = dict(
        line.split("=", 1)
        for line in apply_execution_separation(raw, analysis, snapshot).splitlines()
        if "=" in line
    )
    assert out["runway_gate_mode"] == "CONSERVATIVE_CORE_EDGE_COMPAT"
    assert out["usable_runway"] == "4.00000"
    assert out["usable_runway_ok"] == "0"
    assert out["ea_mode"] == "WATCH_ONLY"
    assert out["execution_authority"] == "NONE"
    assert "INSUFFICIENT_USABLE_RUNWAY" in out["separation_guard"]
