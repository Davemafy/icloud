from app.backtest import closed_before
from app.models import Bar


def test_closed_before_prevents_future_leakage():
    bars=[Bar(ts=0,open=1,high=2,low=0,close=1),Bar(ts=3600,open=1,high=2,low=0,close=1),Bar(ts=7200,open=1,high=2,low=0,close=1)]
    x=closed_before(bars,7199,"H1",10)
    assert [q.ts for q in x]==[0]
    x=closed_before(bars,7200,"H1",10)
    assert [q.ts for q in x]==[0,3600]
