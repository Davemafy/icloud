from datetime import datetime, timedelta, timezone

from app.models import Candle, MarketSnapshot, TimeframeBars


def trend_bars(symbol, tf, start, n=120, base=100.0, step=1.0, bearish=False):
    out=[]
    p=base
    for i in range(n):
        drift=(-step*0.08 if bearish else step*0.08)
        # Inject alternating structure so pivot logic has meaningful swings.
        wave=(0.35*step if i%8<4 else -0.35*step)
        o=p
        c=p+drift+wave*0.15
        h=max(o,c)+step*(0.22+(i%5)*0.01)
        l=min(o,c)-step*(0.22+((i+2)%5)*0.01)
        out.append(Candle(ts=start+timedelta(minutes=i), open=o, high=h, low=l, close=c, volume=100+i))
        p=c
    return TimeframeBars(symbol=symbol,timeframe=tf,bars=out)


def make_snapshot(now=None, dxy_bearish=True, spread=26):
    now=now or datetime.now(timezone.utc)
    start=now-timedelta(hours=3)
    return MarketSnapshot(
        generated_at=now, session="ASIA", spread_points=spread, point_size=0.001,
        xau={
            "D1": trend_bars("XAUUSD","D1",start,base=4400,step=8,bearish=False),
            "H4": trend_bars("XAUUSD","H4",start,base=4400,step=3,bearish=True),
            "H1": trend_bars("XAUUSD","H1",start,base=4400,step=1.5,bearish=True),
            "M15": trend_bars("XAUUSD","M15",start,base=4400,step=.7,bearish=True),
        },
        dxy={
            "D1": trend_bars("DXY","D1",start,base=100,step=.05,bearish=dxy_bearish),
            "H1": trend_bars("DXY","H1",start,base=100,step=.03,bearish=dxy_bearish),
        },
        source="TEST", account_mode="DEMO",
    )
