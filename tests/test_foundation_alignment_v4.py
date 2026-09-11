from datetime import datetime, timedelta, timezone

from app.ai import _user_payload
from app.engine import build_candidate_analysis
from app.institutional_features import closed_bars, fvg_list, psychological_levels
from app.models import Bias, Candle, NewsEvent, TimeframeBars
from tests.helpers import make_snapshot


def test_ai_payload_contains_actual_news_and_deterministic_feature_map():
    snap = make_snapshot()
    snap.news = [NewsEvent(
        event_id="n1", ts=snap.generated_at + timedelta(minutes=10), title="CPI m/m",
        currency="USD", impact="HIGH", released=False, forecast="0.3%", previous="0.2%"
    )]
    base = build_candidate_analysis(snap)
    payload = _user_payload(snap, base)
    assert payload["news_context"][0]["title"] == "CPI m/m"
    assert payload["news_context"][0]["forecast"] == "0.3%"
    assert "institutional_features" in payload
    assert "psychological_levels_xau" in payload["institutional_features"]
    assert "H4" in payload["institutional_features"]["xau"]
    assert "H4" in payload["institutional_features"]["dxy"]


def test_closed_bars_excludes_forming_htf_candle():
    now = datetime(2026, 9, 10, 12, 30, tzinfo=timezone.utc)
    bars = [
        Candle(ts=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc), open=1, high=2, low=.5, close=1.5),
        Candle(ts=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc), open=1.5, high=2.2, low=1.4, close=2.0),
    ]
    series = TimeframeBars(symbol="XAUUSD", timeframe="H4", bars=bars + [bars[0]] * 18)
    # Build a correctly ordered series with enough bars, ending in a 12:00 forming H4 candle.
    seq=[]
    start=datetime(2026,9,7,4,0,tzinfo=timezone.utc)
    for i in range(20):
        ts=start+timedelta(hours=4*i)
        seq.append(Candle(ts=ts,open=10+i,high=11+i,low=9+i,close=10.5+i))
    seq.append(Candle(ts=datetime(2026,9,10,12,0,tzinfo=timezone.utc),open=30,high=31,low=29,close=30.5))
    series=TimeframeBars(symbol="XAUUSD", timeframe="H4", bars=seq)
    out=closed_bars(series, now)
    assert out[-1].ts < datetime(2026,9,10,12,0,tzinfo=timezone.utc)


def test_exact_fvg_and_psychological_levels_are_deterministic():
    t=datetime(2026,9,10,tzinfo=timezone.utc)
    bars=[
        Candle(ts=t,open=100,high=101,low=99,close=100.5),
        Candle(ts=t+timedelta(minutes=15),open=100.5,high=102,low=100,close=101.5),
        Candle(ts=t+timedelta(minutes=30),open=103,high=104,low=102,close=103.5),
    ]
    fvgs=fvg_list(bars, Bias.BULLISH)
    assert fvgs and fvgs[0]["low"] == 101 and fvgs[0]["high"] == 102
    levels=psychological_levels(4367.2)
    assert 4370.0 in levels["10"]


def test_zone_metadata_when_zone_survives_contains_source_and_invalidation():
    analysis=build_candidate_analysis(make_snapshot())
    for z in analysis.zones:
        assert z.instrument == "XAUUSD"
        assert z.invalidation_level is not None
        assert z.invalidation_tf == "M15"
        assert z.source_tf in {"D1>H4>H1", "D1>H4", "H4>H1", "D1>H1", "H1", "H4"}


def test_displacement_origin_prefers_last_opposite_source_candle():
    from app.indicators import displacement_origins
    t = datetime(2026, 9, 10, tzinfo=timezone.utc)
    bars = [
        Candle(ts=t, open=100, high=101, low=99.5, close=100.6, volume=100),
        Candle(ts=t+timedelta(hours=1), open=100.6, high=101.0, low=99.8, close=100.0, volume=100),  # bearish source
        Candle(ts=t+timedelta(hours=2), open=100.0, high=100.8, low=99.9, close=100.5, volume=100),  # same-side base
        Candle(ts=t+timedelta(hours=3), open=100.5, high=104.5, low=100.4, close=104.2, volume=300), # bullish displacement
        Candle(ts=t+timedelta(hours=4), open=104.2, high=104.4, low=103.8, close=104.0, volume=100),
    ]
    # Pad history; keep the crafted launch at the end so it is discovered first.
    pad=[]
    for i in range(20):
        p=90+i*.1
        pad.append(Candle(ts=t-timedelta(hours=30-i),open=p,high=p+.2,low=p-.2,close=p+.05,volume=80))
    all_bars=pad+bars
    zones=displacement_origins(all_bars, Bias.BULLISH, atr_value=2.0, lookback=10, limit=2, body_atr_multiple=0.8)
    assert zones
    low, high, source_idx, disp_idx=zones[0]
    assert all_bars[source_idx].close <= all_bars[source_idx].open
    assert all_bars[source_idx].ts == bars[1].ts
    assert all_bars[disp_idx].ts == bars[3].ts


def test_dxy_d1_macro_conflict_neutralizes_intermarket_implication():
    from app.engine import _dxy_implication
    from app.models import DxyImplication
    # H4/H1 dollar bullish would normally support bearish XAU, but bearish D1 makes
    # the dollar stack mixed, so deterministic execution quality stays neutral.
    assert _dxy_implication(Bias.BEARISH, Bias.BEARISH, Bias.BULLISH, Bias.BULLISH) == DxyImplication.NEUTRAL
    assert _dxy_implication(Bias.BEARISH, Bias.BULLISH, Bias.BULLISH, Bias.BULLISH) == DxyImplication.SUPPORTS


def _guard_analysis(now, direction=None):
    from app.models import Direction, Grade, InstitutionalAnalysis, Zone, DxyImplication
    import uuid
    direction = direction or Direction.BUY_ONLY
    if direction == Direction.BUY_ONLY:
        low, high, level, sweep = 99.0, 100.0, 99.0, "SSL"
    else:
        low, high, level, sweep = 100.0, 101.0, 101.0, "BSL"
    zone = Zone(
        zone_id="Z_GUARD", direction=direction, zone_low=low, zone_high=high, grade=Grade.A,
        source_tf="H1", requires_sweep=sweep, invalidation="M15 acceptance", invalidation_level=level,
        invalidation_tf="M15"
    )
    return InstitutionalAnalysis(
        analysis_id=str(uuid.uuid4()), generated_at=now-timedelta(minutes=45), valid_until=now+timedelta(hours=1),
        snapshot_id="x", session="NEW_YORK", current_xau_price=100, current_dxy_price=99, spread_points=10,
        xau_m15_atr=1.0,
        dxy_d1_bias=Bias.NEUTRAL, dxy_h4_bias=Bias.NEUTRAL, dxy_h1_bias=Bias.NEUTRAL,
        xau_d1_bias=Bias.NEUTRAL, xau_h4_bias=Bias.NEUTRAL, xau_h1_bias=Bias.NEUTRAL,
        xau_m15_context=Bias.NEUTRAL, overall_bias=Bias.NEUTRAL, dxy_implication=DxyImplication.NEUTRAL,
        primary_liquidity="x", zones=[zone], ea_mode=direction, source_fingerprint="x", approved=True,
    )


def _m15_series(now, overrides=None, atr_value=1.0):
    overrides = overrides or {}
    bars=[]
    start=now-timedelta(hours=5)
    for i in range(20):
        ts=start+timedelta(minutes=15*i)
        vals=overrides.get(i, (100.2, 100.5, 99.7, 100.2))
        bars.append(Candle(ts=ts,open=vals[0],high=vals[1],low=vals[2],close=vals[3],volume=100))
    return TimeframeBars(symbol="XAUUSD", timeframe="M15", bars=bars, atr=atr_value)


def test_live_zone_guard_blocks_one_strong_m15_acceptance_candle():
    from app.models import Direction
    from app.service import apply_live_zone_guard
    now=datetime(2026,9,10,16,30,tzinfo=timezone.utc)
    snap=make_snapshot(now=now)
    # Bar index 10 runs 16:00-16:15. It closes below BUY distal=99.0 with
    # 1.0/1.4 = 71.4% of its real body beyond the boundary and body > 0.40 ATR.
    snap.xau["M15"]=_m15_series(now,{18:(99.4,99.5,97.8,98.0)})
    analysis=_guard_analysis(now,Direction.BUY_ONLY)
    guarded=apply_live_zone_guard(analysis,snap)
    assert guarded.ea_mode == Direction.NO_TRADE
    assert guarded.zones == []
    assert any(i.code == "LIVE_M15_ZONE_INVALIDATED" for i in guarded.validator_issues)


def test_live_zone_guard_ignores_wick_only_m15_penetration():
    from app.models import Direction
    from app.service import apply_live_zone_guard
    now=datetime(2026,9,10,16,30,tzinfo=timezone.utc)
    snap=make_snapshot(now=now)
    # Wick trades below 99.0 but the real body closes back inside the demand zone.
    snap.xau["M15"]=_m15_series(now,{18:(99.5,99.8,98.0,99.4)})
    analysis=_guard_analysis(now,Direction.BUY_ONLY)
    guarded=apply_live_zone_guard(analysis,snap)
    assert guarded.ea_mode == Direction.BUY_ONLY
    assert len(guarded.zones) == 1
    assert not any(i.code == "LIVE_M15_ZONE_INVALIDATED" for i in guarded.validator_issues)


def test_live_zone_guard_does_not_use_h1_close_as_intraday_gate():
    from app.models import Direction
    from app.service import apply_live_zone_guard
    now=datetime(2026,9,10,16,30,tzinfo=timezone.utc)
    snap=make_snapshot(now=now)
    snap.xau["M15"]=_m15_series(now)
    # Deliberately place an H1 close below the BUY boundary. v4.1 does not use
    # H1/H4 as the live intraday permission gate; full reanalysis handles HTF retirement.
    h1=[]
    start=now-timedelta(hours=30)
    for i in range(30):
        ts=start+timedelta(hours=i)
        h1.append(Candle(ts=ts,open=100.2,high=100.5,low=99.5,close=100.0,volume=100))
    h1[-2]=Candle(ts=now-timedelta(hours=2),open=100.0,high=100.2,low=97.5,close=98.0,volume=120)
    snap.xau["H1"]=TimeframeBars(symbol="XAUUSD",timeframe="H1",bars=h1,atr=1.0)
    analysis=_guard_analysis(now,Direction.BUY_ONLY)
    guarded=apply_live_zone_guard(analysis,snap)
    assert guarded.ea_mode == Direction.BUY_ONLY
    assert len(guarded.zones) == 1


def test_live_zone_guard_two_meaningful_m15_closes_establish_acceptance():
    from app.models import Direction
    from app.service import apply_live_zone_guard
    now=datetime(2026,9,10,16,30,tzinfo=timezone.utc)
    snap=make_snapshot(now=now)
    # Each candle has 50% of its body below the BUY boundary, so neither meets
    # the one-candle 60% rule. Two consecutive meaningful closes still establish acceptance.
    snap.xau["M15"]=_m15_series(now,{17:(99.2,99.3,98.7,98.8),18:(99.2,99.3,98.7,98.8)})
    analysis=_guard_analysis(now,Direction.BUY_ONLY)
    guarded=apply_live_zone_guard(analysis,snap)
    assert guarded.ea_mode == Direction.NO_TRADE
    assert guarded.zones == []
    assert any("consecutive M15 closes" in i.message for i in guarded.validator_issues)


def test_live_zone_guard_weak_single_m15_close_does_not_invalidate():
    from app.models import Direction
    from app.service import apply_live_zone_guard
    now=datetime(2026,9,10,16,30,tzinfo=timezone.utc)
    snap=make_snapshot(now=now)
    # Closes just below the BUY boundary with only a 0.25 body and 20% body beyond.
    snap.xau["M15"]=_m15_series(now,{18:(99.20,99.25,98.90,98.95)})
    analysis=_guard_analysis(now,Direction.BUY_ONLY)
    guarded=apply_live_zone_guard(analysis,snap)
    assert guarded.ea_mode == Direction.BUY_ONLY
    assert len(guarded.zones) == 1


def test_live_zone_guard_sell_zone_uses_same_m15_acceptance_logic():
    from app.models import Direction
    from app.service import apply_live_zone_guard
    now=datetime(2026,9,10,16,30,tzinfo=timezone.utc)
    snap=make_snapshot(now=now)
    # SELL distal=101.0. 71.4% of 1.4 body is above the boundary.
    snap.xau["M15"]=_m15_series(now,{18:(100.6,102.3,100.5,102.0)})
    analysis=_guard_analysis(now,Direction.SELL_ONLY)
    guarded=apply_live_zone_guard(analysis,snap)
    assert guarded.ea_mode == Direction.NO_TRADE
    assert guarded.zones == []
    assert any(i.code == "LIVE_M15_ZONE_INVALIDATED" for i in guarded.validator_issues)
