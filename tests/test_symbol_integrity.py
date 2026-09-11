from datetime import datetime, timedelta, timezone
import pytest
from app.models import Candle, MarketSnapshot, TimeframeBars


def tf(symbol, timeframe, base, atr=1.0):
    t=datetime(2026,9,10,tzinfo=timezone.utc)
    bars=[]
    for i in range(20):
        p=base+i*0.01
        bars.append(Candle(ts=t+timedelta(minutes=i),open=p,high=p+0.1,low=p-0.1,close=p,volume=1))
    return TimeframeBars(symbol=symbol,timeframe=timeframe,bars=bars,atr=atr)


def packet(xau_symbol='XAUUSD', bid=4357.0, ask=4357.2):
    return dict(
        schema_version=3, generated_at=datetime.now(timezone.utc), session='NEW_YORK',
        snapshot_kind='LIVE_UPDATE', snapshot_reason='LIVE', source='MT5_BRIDGE_V1_23',
        bid=bid, ask=ask, spread_points=20, point_size=.01,
        xau={k:tf(xau_symbol,k,4357,13 if k=='M15' else 20) for k in ('D1','H4','H1','M15')},
        dxy={k:tf('DXYUSD',k,99,.1) for k in ('D1','H4','H1')},
    )


def test_bridge_rejects_xau_dxy_symbol_collision():
    with pytest.raises(ValueError, match='symbol collision'):
        MarketSnapshot.model_validate(packet(xau_symbol='DXYUSD', bid=99.0, ask=99.05))


def test_bridge_rejects_dxy_quote_as_xau_quote():
    with pytest.raises(ValueError, match='XAU quote mismatch'):
        MarketSnapshot.model_validate(packet(bid=99.0, ask=99.05))


def test_bridge_accepts_consistent_xau_quote():
    snap=MarketSnapshot.model_validate(packet())
    assert snap.bid == 4357.0
