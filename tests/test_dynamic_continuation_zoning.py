from app import dynamic_continuation_zoning as policy
from app.models import Analysis, Bar, Direction, Grade, LiquidityLevel, MarketSnapshot, Zone, ZoneState


def _snapshot(mid: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(sent_at=20_000,bid=mid-0.1,ask=mid+0.1,spread_points=20.0,point=0.01,atr_h1=10.0,atr_m15=2.0)


def _zone(zone_id,direction,grade,touches,core_low,core_high,zone_low,zone_high):
    return Zone(zone_id=zone_id,original_direction=direction,flip_direction=direction.opposite(),setup_type="CONTINUATION" if direction==Direction.SELL else "REVERSAL",source_tf="H1",grade=grade,state=ZoneState.ACTIVE,core_low=core_low,core_high=core_high,core_method="ARMED|TEST",location_score=8.0,zone_low=zone_low,zone_high=zone_high,touch_count=touches,confluences=["LIQUIDITY_IN_MARKED_ZONE"],independent_confluence_count=1,source_ts=19_000,invalidation_level=zone_high if direction==Direction.SELL else zone_low,invalidation_rule="test",original_target1=80.0 if direction==Direction.SELL else 120.0)


def _analysis(zones):
    return Analysis(analysis_id="A_TEST",generated_at=20_000,snapshot_at=20_000,overall_bias=Direction.SELL,zones=zones,selected_zone_id=zones[0].zone_id if zones else "",liquidity_map=[],execution_policy={"public_zone_map":{}})


def _event():
    return policy.ContinuationEvent(direction=Direction.SELL,source_tf="H1",source_ts=19_100,displacement_ts=19_200,strength=2.2,fvg_low=104.0,fvg_high=105.0,age_bars=1)


def test_high_touch_countertrend_buy_is_not_demoted_by_touch_count(monkeypatch):
    sell=_zone("SELL_REMOTE",Direction.SELL,Grade.A_PLUS,0,130,131,128,132); buy=_zone("BUY_USED",Direction.BUY,Grade.B_PLUS,30,99,101,97,103); analysis=_analysis([sell,buy]); analysis.selected_zone_id="SELL_REMOTE"
    monkeypatch.setattr(policy,"active_owner_snapshot",lambda now:None); monkeypatch.setattr(policy,"_recent_events",lambda snapshot,direction:[_event()]); monkeypatch.setattr(policy,"_expansion_state",lambda snapshot,context,events:{"aligned":True,"d1":"SELL","h1":"SELL","h4":"SELL","recent_event_count":1}); monkeypatch.setattr(policy,"_build_dynamic_zone",lambda event,analysis,snapshot:None)
    policy.apply_dynamic_continuation_rezone(analysis,_snapshot())
    assert [z.zone_id for z in analysis.zones]==["SELL_REMOTE","BUY_USED"]
    meta=analysis.execution_policy["dynamic_continuation_rezone"]; assert meta["demoted_context_zones"]==[]; assert meta["touch_count_can_demote_zone"] is False


def test_nearer_fresh_continuation_replaces_remote_primary(monkeypatch):
    remote=_zone("SELL_REMOTE",Direction.SELL,Grade.A_PLUS,0,130,131,128,132); fresh_buy=_zone("BUY_FRESH",Direction.BUY,Grade.A_PLUS,0,90,91,88,93); analysis=_analysis([remote,fresh_buy]); dynamic=_zone("DC_H1_SELL_19200",Direction.SELL,Grade.A,0,104,105,103,106); dynamic.core_method="ARMED|DYNAMIC_CONTINUATION_REZONE|FVG_BOS_LIQUIDITY_CENTERED"; dynamic.confluences=["DYNAMIC_CONTINUATION_REZONE","LIQUIDITY_CENTERED_CORE"]
    monkeypatch.setattr(policy,"active_owner_snapshot",lambda now:None); monkeypatch.setattr(policy,"_recent_events",lambda snapshot,direction:[_event()]); monkeypatch.setattr(policy,"_expansion_state",lambda snapshot,context,events:{"aligned":True,"d1":"SELL","h1":"SELL","h4":"SELL","recent_event_count":1}); monkeypatch.setattr(policy,"_build_dynamic_zone",lambda event,analysis,snapshot:dynamic)
    policy.apply_dynamic_continuation_rezone(analysis,_snapshot())
    ids=[z.zone_id for z in analysis.zones]; assert "SELL_REMOTE" not in ids; assert "DC_H1_SELL_19200" in ids; assert "BUY_FRESH" in ids; assert analysis.selected_zone_id=="DC_H1_SELL_19200"
    meta=analysis.execution_policy["dynamic_continuation_rezone"]; assert meta["replaced_primary"]["zone_id"]=="SELL_REMOTE"; assert meta["dynamic_primary"]["zone_id"]=="DC_H1_SELL_19200"


def test_acquired_thesis_protects_map_from_rezoning(monkeypatch):
    sell=_zone("SELL_REMOTE",Direction.SELL,Grade.A_PLUS,0,130,131,128,132); buy=_zone("BUY_USED",Direction.BUY,Grade.B_PLUS,3,99,101,97,103); analysis=_analysis([sell,buy])
    monkeypatch.setattr(policy,"active_owner_snapshot",lambda now:{"reaction_key":"BUY|H1|1","ownership_acquired_at":1}); monkeypatch.setattr(policy,"_recent_events",lambda snapshot,direction:[_event()]); monkeypatch.setattr(policy,"_expansion_state",lambda snapshot,context,events:{"aligned":True,"d1":"SELL","h1":"SELL","h4":"SELL","recent_event_count":1})
    policy.apply_dynamic_continuation_rezone(analysis,_snapshot()); assert [z.zone_id for z in analysis.zones]==["SELL_REMOTE","BUY_USED"]; assert analysis.execution_policy["dynamic_continuation_rezone"]["owner_protected"] is True


def test_dynamic_fvg_mitigation_clock_waits_for_third_candle_close():
    event=_event(); assert policy._event_ready_ts(event)==event.displacement_ts+2*3600


def test_legacy_synthetic_liquidity_centered_geometry_fails_closed_under_master_sniper():
    # Master Sniper authority disables the old fixed-width dynamic-zone factory.
    # A continuation must now be published by the structural source/liquidity map,
    # not manufactured from an FVG midpoint plus synthetic width padding.
    assert policy._liquidity_centered_geometry(_event(),104.5,_snapshot()) is None


def test_fvg_cannot_create_dynamic_zone_without_structural_liquidity(monkeypatch):
    analysis=_analysis([]); analysis.liquidity_map=[LiquidityLevel(label="PSY",price=104.5,side="ABOVE",source_tf="PSY",distance=4.5)]; monkeypatch.setattr(policy,"_touches",lambda *args,**kwargs:0)
    assert policy._build_dynamic_zone(_event(),analysis,_snapshot()) is None


def test_sync_public_map_preserves_structural_aplus_gap_for_surviving_zone():
    sell=_zone("PZ_H1_SELL_16",Direction.SELL,Grade.A,0,4303.77,4309.77,4302.19,4324.19); sell.notes.extend(["structural_grade:A","current_execution_grade:A","grade_degrade_reason:NONE","structural_aplus_missing:score_ge_8","structural_a_missing:NONE","grade_location_score:4.2200","grade_source_strength:2.2600"]); analysis=_analysis([sell]); analysis.execution_policy["public_zone_map"]={"sell":{"zone_id":"PZ_H1_SELL_16","structural_grade":"A","grade":"A","structural_aplus_missing":"score_ge_8","structural_a_missing":"NONE","grade_degrade_reason":"NONE"}}
    policy._sync_public_map(analysis); row=analysis.execution_policy["public_zone_map"]["sell"]
    assert row["structural_grade"]=="A"; assert row["grade"]=="A"; assert row["current_execution_grade"]=="A"; assert row["structural_aplus_missing"]=="score_ge_8"; assert row["structural_a_missing"]=="NONE"; assert row["grade_location_score"]==4.22; assert row["grade_source_strength"]==2.26


def test_source_exact_dynamic_builder_uses_actual_source_candle(monkeypatch):
    from app import institutional_two_zone as zoning

    event = _event()
    snap = _snapshot()
    snap.sent_at = event.displacement_ts + 3 * 3600
    snap.xau_h1 = [
        Bar(ts=event.source_ts, open=106.0, high=107.5, low=103.5, close=104.0, tick_volume=100),
    ]
    analysis = _analysis([])
    analysis.liquidity_map = [
        LiquidityLevel(label="H1_BSL", price=107.0, side="ABOVE", source_tf="H1", distance=7.0)
    ]
    built = _zone("EXPECTED", Direction.SELL, Grade.A, 0, 104.0, 106.0, 103.5, 107.5)
    captured = {}

    def fake_candidate_zone(candidate, snapshot, liq, context, index):
        captured["candidate"] = candidate
        return built, {}

    monkeypatch.setattr(zoning, "_candidate_zone", fake_candidate_zone)
    monkeypatch.setattr(zoning, "_volume_expansion", lambda bars, ts: True)

    out = policy._build_dynamic_zone(event, analysis, snap)

    assert out is built
    candidate = captured["candidate"]
    assert candidate.core_low == 104.0
    assert candidate.core_high == 106.0
    assert candidate.zone_low == 103.5
    assert candidate.zone_high == 107.5
    assert candidate.source_ts == event.source_ts
    assert candidate.source_ready_ts == policy._event_ready_ts(event)
    assert "DYNAMIC_CONTINUATION_SOURCE_EXACT" in out.confluences
    assert "NO_SYNTHETIC_ZONE_EXPANSION" in out.confluences
    assert "LIQUIDITY_CENTERED_CORE" not in out.confluences


def test_neutral_d1_can_use_confirmed_h1_h4_expansion(monkeypatch):
    analysis = _analysis([])
    analysis.overall_bias = Direction.NEUTRAL
    sell_event = _event()

    def fake_events(snapshot, direction):
        return [sell_event] if direction == Direction.SELL else []

    def fake_expansion(snapshot, direction, events):
        return {
            "aligned": bool(events and direction == Direction.SELL),
            "d1": direction.value,
            "h1": "SELL",
            "h4": "SELL",
            "recent_event_count": len(events),
            "strong_recent_h1_displacement": bool(events),
        }

    monkeypatch.setattr(policy, "_recent_events", fake_events)
    monkeypatch.setattr(policy, "_expansion_state", fake_expansion)
    monkeypatch.setattr(policy, "structure_bias", lambda bars: Direction.SELL)

    direction, events, meta = policy._continuation_context(analysis, _snapshot())

    assert direction == Direction.SELL
    assert events == [sell_event]
    assert meta["d1"] == "NEUTRAL"
    assert meta["continuation_direction"] == "SELL"


def test_dynamic_audit_declares_source_exact_not_synthetic(monkeypatch):
    analysis = _analysis([_zone("SELL_REMOTE", Direction.SELL, Grade.A, 0, 130, 131, 128, 132)])
    monkeypatch.setattr(policy, "active_owner_snapshot", lambda now: None)
    monkeypatch.setattr(
        policy,
        "_continuation_context",
        lambda analysis, snapshot: (
            Direction.SELL,
            [_event()],
            {"aligned": True, "d1": "NEUTRAL", "h1": "SELL", "h4": "SELL", "recent_event_count": 1},
        ),
    )
    monkeypatch.setattr(policy, "_build_dynamic_zone", lambda event, analysis, snapshot: None)

    policy.apply_dynamic_continuation_rezone(analysis, _snapshot())

    meta = analysis.execution_policy["dynamic_continuation_rezone"]
    assert meta["source_exact_geometry"] is True
    assert meta["synthetic_fvg_centered_geometry"] is False
    assert meta["d1_neutral_can_use_confirmed_h1_h4_expansion"] is True
