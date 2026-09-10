from datetime import datetime, timedelta, timezone

from app.engine import build_candidate_analysis
from app.models import AIDraft, AIZoneDecision, Bias, Direction, DxyImplication, Grade
from app.scheduler import session_run_keys
from app.validator import merge_and_validate
from tests.helpers import make_snapshot


def draft_for(base, zone_ids=None):
    zone_ids = zone_ids if zone_ids is not None else [z.zone_id for z in base.zones]
    return AIDraft(
        dxy_d1_bias=base.dxy_d1_bias,dxy_h4_bias=base.dxy_h4_bias,dxy_h1_bias=base.dxy_h1_bias,
        xau_d1_bias=base.xau_d1_bias,xau_h4_bias=base.xau_h4_bias,xau_h1_bias=base.xau_h1_bias,xau_m15_context=base.xau_m15_context,
        overall_bias=base.overall_bias,dxy_implication=base.dxy_implication,primary_liquidity=base.primary_liquidity,
        no_trade=False,no_trade_reason=None,
        zone_decisions=[AIZoneDecision(candidate_zone_id=zid,use_zone=True,grade=Grade.A,direction=next(z.direction for z in base.zones if z.zone_id==zid),required_sweep=next(z.requires_sweep for z in base.zones if z.zone_id==zid),min_displacement_atr=1.0,institutional_interpretation="candidate selected",execution_condition="M1 sweep then MSS then displacement then fresh FVG/OB pullback",downgrade_reason=None) for zid in zone_ids],
        expected_sequence="HTF -> zone -> sweep -> M1 MSS -> displacement -> FVG/OB -> pullback",
        retail_trap="breakout chase",overall_invalidation="HTF invalidation",trader_brief="wait for M1",
    )


def test_dxy_conflict_downgrades_a_zone():
    snap=make_snapshot(dxy_bearish=True)
    base=build_candidate_analysis(snap)
    if not base.zones:
        return
    d=draft_for(base)
    d.dxy_implication=DxyImplication.CONFLICTS
    out=merge_and_validate(snap,base,d,{"model":"test"})
    assert all(z.grade not in {Grade.A,Grade.A_PLUS} for z in out.zones)


def test_unknown_ai_zone_is_rejected_and_not_added():
    snap=make_snapshot()
    base=build_candidate_analysis(snap)
    d=AIDraft(
        dxy_d1_bias=base.dxy_d1_bias,dxy_h4_bias=base.dxy_h4_bias,dxy_h1_bias=base.dxy_h1_bias,xau_d1_bias=base.xau_d1_bias,xau_h4_bias=base.xau_h4_bias,xau_h1_bias=base.xau_h1_bias,xau_m15_context=base.xau_m15_context,
        overall_bias=base.overall_bias,dxy_implication=base.dxy_implication,primary_liquidity=base.primary_liquidity,no_trade=False,no_trade_reason=None,
        zone_decisions=[AIZoneDecision(candidate_zone_id="INVENTED_4352",use_zone=True,grade=Grade.A,direction=Direction.BUY_ONLY,required_sweep="SSL",min_displacement_atr=1.0,institutional_interpretation="bad",execution_condition="bad",downgrade_reason=None)],
        expected_sequence="x",retail_trap="x",overall_invalidation="x",trader_brief="x")
    out=merge_and_validate(snap,base,d,{"model":"test"})
    assert not any(z.zone_id=="INVENTED_4352" for z in out.zones)
    assert any(i.code=="AI_UNKNOWN_ZONE" for i in out.validator_issues)


def test_stale_snapshot_forces_no_trade():
    snap=make_snapshot(now=datetime.now(timezone.utc)-timedelta(hours=2))
    base=build_candidate_analysis(snap)
    out=merge_and_validate(snap,base,None,None)
    assert out.ea_mode==Direction.NO_TRADE
    assert any(i.code=="STALE_SNAPSHOT" for i in out.validator_issues)


def test_asia_pre_session_scheduler_key():
    # Default Asia start is 00:00 WAT, lead 10 min => 23:50 WAT on previous date => 22:50 UTC.
    now=datetime(2026,9,8,22,50,5,tzinfo=timezone.utc)
    keys=session_run_keys(now)
    assert any(name=="ASIA" for _,name in keys)

def test_post_news_scheduler_after_cooldown_uses_event_time():
    from app.db import DB
    from app.scheduler import post_news_run_keys
    event_ts=datetime(2026,9,9,12,30,0,tzinfo=timezone.utc)
    DB.upsert_news({
        "event_id":"test-news-cooldown-001","ts":event_ts.isoformat(),"currency":"USD","impact":"HIGH",
        "title":"Test High Impact USD Event","released":True,"actual":"1","forecast":"1","previous":"1","source":"test"
    })
    now=event_ts+timedelta(minutes=5,seconds=5)
    keys=post_news_run_keys(now)
    assert any(k.startswith("news:test-news-cooldown-001:") and title=="Test High Impact USD Event" and ts==event_ts for k,title,ts in keys)


def test_asia_scheduler_catches_up_at_2357_wat():
    # Asia starts 00:00 WAT; nominal analysis is 23:50. With the default
    # 20-minute catch-up window, 23:57 WAT must still be eligible.
    now=datetime(2026,9,9,22,57,0,tzinfo=timezone.utc)
    keys=session_run_keys(now)
    assert any(name=="ASIA" and key.endswith("2026-09-10") for key,name in keys)


def test_failed_scheduler_attempt_does_not_block_retry():
    from app.db import DB
    key="session:ASIA:2099-01-01-test-retry"
    DB.mark_scheduler_run(key,"session","failed","temporary failure")
    assert DB.scheduler_ran(key) is False
    DB.mark_scheduler_run(key,"session","success","ok")
    assert DB.scheduler_ran(key) is True



def test_active_london_session_is_recovery_due_after_pre_window():
    # 09:23 WAT on 10 Sep 2026 is inside the active London session, long after
    # the 07:50-08:10 pre-session window. It must still be eligible for one
    # automatic recovery analysis if the session key has not succeeded.
    from app.scheduler import active_session, session_run_candidates
    now = datetime(2026, 9, 10, 8, 23, 0, tzinfo=timezone.utc)
    active = active_session(now)
    assert active and active["session"] == "LONDON"
    cands = session_run_candidates(now)
    assert any(c["session"] == "LONDON" and c["mode"] == "active_recovery" for c in cands)


def test_upcoming_pre_session_has_priority_over_outgoing_recovery():
    # 12:55 WAT: New York pre-session analysis is due. Do not also recover a
    # missed London plan and spend two AI calls back-to-back.
    from app.scheduler import session_run_candidates
    now = datetime(2026, 9, 10, 11, 55, 0, tzinfo=timezone.utc)
    cands = session_run_candidates(now)
    assert any(c["session"] == "NEW_YORK" and c["mode"] == "pre_session" for c in cands)
    assert not any(c["session"] == "LONDON" for c in cands)


def test_scheduler_status_keeps_active_session_visible_for_recovery():
    from app.scheduler import scheduler_status
    now = datetime(2098, 9, 10, 8, 23, 0, tzinfo=timezone.utc)
    status = scheduler_status(now)
    london = next(x for x in status["sessions"] if x["session"] == "LONDON")
    assert london["session_start"].startswith("2098-09-10")
    assert london["status"] in {"RECOVERY_DUE", "DONE"}
