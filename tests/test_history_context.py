from datetime import datetime, timedelta, timezone

from app.ai import _compact_bars
from app.models import MarketSnapshot
from app.service import history_status
from tests.helpers import make_snapshot, trend_bars


def make_full_history(now=None):
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=365)
    xau = {
        "D1": trend_bars("XAUUSD", "D1", start, n=280, base=4300, step=8, bearish=False),
        "H4": trend_bars("XAUUSD", "H4", start, n=600, base=4300, step=3, bearish=True),
        "H1": trend_bars("XAUUSD", "H1", start, n=600, base=4300, step=1.5, bearish=True),
        "M15": trend_bars("XAUUSD", "M15", start, n=520, base=4300, step=.7, bearish=True),
    }
    dxy = {
        "D1": trend_bars("DXYUSD", "D1", start, n=280, base=100, step=.05, bearish=True),
        "H4": trend_bars("DXYUSD", "H4", start, n=600, base=100, step=.04, bearish=True),
        "H1": trend_bars("DXYUSD", "H1", start, n=600, base=100, step=.03, bearish=True),
    }
    profile = {f"XAU:{tf}": len(s.bars) for tf, s in xau.items()}
    profile.update({f"DXY:{tf}": len(s.bars) for tf, s in dxy.items()})
    return MarketSnapshot(
        schema_version=3,
        generated_at=now,
        session="LONDON",
        snapshot_kind="FULL_HISTORY",
        snapshot_reason="PRE_SESSION:LONDON",
        xau=xau,
        dxy=dxy,
        bid=4395.1,
        ask=4395.3,
        spread_points=20,
        spread_price=.2,
        point_size=.01,
        atr_period=14,
        history_profile=profile,
        source="TEST_V3",
        account_mode="DEMO",
    )


def test_history_profile_is_ready_at_requested_depth():
    snap = make_full_history()
    status = history_status(snap)
    assert status["ready"] is True
    assert status["counts"]["XAU:D1"] == 280
    assert status["counts"]["XAU:H4"] == 600
    assert status["counts"]["XAU:M15"] == 520
    assert status["counts"]["DXY:H4"] == 600
    assert status["counts"]["DXY:H1"] == 600


def test_v3_advertised_short_history_is_not_ready():
    snap = make_snapshot()
    snap.snapshot_kind = "FULL_HISTORY"
    snap.snapshot_reason = "PRE_SESSION:LONDON"
    snap.history_profile = {f"XAU:{tf}": len(s.bars) for tf, s in snap.xau.items()}
    snap.history_profile.update({f"DXY:{tf}": len(s.bars) for tf, s in snap.dxy.items()})
    status = history_status(snap)
    assert status["ready"] is False
    assert "XAU:H4" in status["missing"]


def test_ai_payload_is_not_truncated_to_80_bars_anymore():
    snap = make_full_history()
    packed = _compact_bars(snap)
    assert packed["xau"]["D1"]["bar_count"] == 280
    assert len(packed["xau"]["H4"]["bars"]) == 600
    assert len(packed["xau"]["M15"]["bars"]) == 520
    assert len(packed["dxy"]["H4"]["bars"]) == 600
    assert len(packed["dxy"]["H1"]["bars"]) == 600


def test_dxy_h4_is_required_for_protocol_v3_history():
    snap = make_full_history()
    del snap.dxy["H4"]
    snap.history_profile.pop("DXY:H4", None)
    status = history_status(snap)
    assert status["ready"] is False
    assert "DXY:H4" in status["missing"]
