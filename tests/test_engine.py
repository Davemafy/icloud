from app.engine import evaluate_zone_state, _cluster, Origin
from app.models import Bar, Direction, Zone, ZoneState, Grade


def b(ts,o,h,l,c): return Bar(ts=ts,open=o,high=h,low=l,close=c)


def test_cluster_uses_strict_overlap():
    a=Origin(Direction.SELL,100,110,1,"D1",1,2.0,True)
    c=Origin(Direction.SELL,104,108,2,"H4",2,2.0,True)
    d=Origin(Direction.SELL,105,107,3,"H1",3,2.0,True)
    lo,hi,m=_cluster([a,c,d],d)
    assert (lo,hi)==(105,107)
    assert m=="STRICT_PREEXISTING_HTF_OVERLAP"


def zone():
    return Zone(zone_id="Z",original_direction=Direction.SELL,flip_direction=Direction.BUY,setup_type="CONTINUATION",source_tf="H4>H1",grade=Grade.A,state=ZoneState.ACTIVE,core_low=100,core_high=102,core_method="X",location_score=8,zone_low=99,zone_high=103,invalidation_level=103,invalidation_rule="x")


def test_wick_only_does_not_flip():
    bars=[b(1,101,102,100,101),b(2,102,104,101,102.5),b(3,102.5,104.5,102,102.8)]
    assert evaluate_zone_state(zone(),bars,1.0)==ZoneState.ACTIVE


def test_strong_m15_acceptance_creates_flip_candidate():
    bars=[b(1,101,102,100,101),b(2,102,104,101.5,103.8),b(3,102.8,104.5,102.7,104.0)]
    assert evaluate_zone_state(zone(),bars,1.0)==ZoneState.FAILED_FLIP_CANDIDATE
