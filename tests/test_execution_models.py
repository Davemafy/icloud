from types import SimpleNamespace

from app.execution_models import build_execution_overlay, classify_regime
from app.models import Analysis, Bar, Direction, Grade, MarketSnapshot, Zone


def _bars(n=180, start=4300.0, step=0.35):
    out=[]
    p=start
    for i in range(n):
        q=p+step
        out.append(Bar(ts=1_700_000_000+i*900, open=p, high=max(p,q)+0.20, low=min(p,q)-0.20, close=q, tick_volume=100+i))
        p=q
    return out


def _snapshot():
    b=_bars()
    return MarketSnapshot(sent_at=1_700_200_000,bid=b[-1].close,ask=b[-1].close+0.30,spread_points=30,point=0.01,atr_h1=4.0,atr_m15=1.0,xau_d1=b[-80:],xau_h4=b[-120:],xau_h1=b[-160:],xau_m15=b,dxy_d1=b[-80:],dxy_h4=b[-120:],dxy_h1=b[-160:])


def test_regime_classifier_returns_supported_regime():
    r=classify_regime(_snapshot())
    assert r["name"] in {"UNKNOWN","EXHAUSTION","EXPANSION","COMPRESSION","TREND","RANGE"}
    assert 0.0 <= r["confidence"] <= 1.0
    assert "vwap_proxy" in r


def test_overlay_keeps_orderflow_disabled_without_centralized_feed():
    s=_snapshot()
    z=Zone(zone_id="Z1",original_direction=Direction.BUY,flip_direction=Direction.SELL,setup_type="CONTINUATION",source_tf="D1>H4>H1",grade=Grade.A,state="ACTIVE",core_low=s.mid-2,core_high=s.mid-1,core_method="TEST",location_score=8,zone_low=s.mid-3,zone_high=s.mid-0.5,invalidation_level=s.mid-3.1)
    a=Analysis(analysis_id="A1",generated_at=s.sent_at,snapshot_at=s.sent_at,zones=[z],selected_zone_id="Z1")
    o=build_execution_overlay(s,a,"TEST")
    assert o["rules"]["htf_location_remains_authority"] is True
    assert o["models"]["order_flow_imbalance"] is False
    assert o["parameters"]["alternate_model_risk_multiplier"] <= 1.0
