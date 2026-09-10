from datetime import datetime, timedelta, timezone
from app.models import Candle, MarketSnapshot, TimeframeBars
from app.engine import analyze


def bars(symbol, tf, start, n=120, step=1.0, bearish=False):
    out=[]
    p=100.0
    for i in range(n):
        drift = -step*0.05 if bearish else step*0.05
        o=p
        c=p+drift
        h=max(o,c)+step*0.2
        l=min(o,c)-step*0.2
        out.append(Candle(ts=start+timedelta(minutes=i), open=o, high=h, low=l, close=c, volume=1))
        p=c
    return TimeframeBars(symbol=symbol, timeframe=tf, bars=out)


def test_analysis_runs():
    t=datetime(2026,9,9,tzinfo=timezone.utc)
    snap=MarketSnapshot(
        generated_at=t, session="ASIA", spread_points=26,
        xau={
            "D1": bars("XAUUSD","D1",t,bearish=False),
            "H4": bars("XAUUSD","H4",t,bearish=True),
            "H1": bars("XAUUSD","H1",t,bearish=True),
            "M15": bars("XAUUSD","M15",t,bearish=True),
        },
        dxy={
            "D1": bars("DXY","D1",t,step=0.05,bearish=True),
            "H4": bars("DXY","H4",t,step=0.05,bearish=True),
            "H1": bars("DXY","H1",t,step=0.05,bearish=True),
        },
    )
    a=analyze(snap)
    assert a.spread_points == 26
    assert a.current_xau_price > 0
