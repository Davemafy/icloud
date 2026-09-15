from types import SimpleNamespace

from app.mt5_zone_render import mt5_zone_render_text


class V:
    def __init__(self, value):
        self.value = value


def _kv(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def _zone(zid, direction, low, high, core_low, core_high, method, grade, source_tf, source_ts, touches):
    return SimpleNamespace(
        zone_id=zid,
        original_direction=V(direction),
        state=V("ACTIVE"),
        core_method=method,
        grade=V(grade),
        source_tf=source_tf,
        source_ts=source_ts,
        touch_count=touches,
        zone_low=low,
        zone_high=high,
        core_low=core_low,
        core_high=core_high,
    )


def test_render_feed_contains_primary_core_envelope_and_active_thesis():
    buy = _zone("BUY_1", "BUY", 4248.57, 4288.57, 4253.57, 4270.98, "WATCH|PROMPT", "B+", "H4>H1", 100, 2)
    sell = _zone("SELL_1", "SELL", 4323.34, 4360.40, 4327.52, 4337.52, "ARMED|PROMPT", "A", "H1", 200, 1)
    a = SimpleNamespace(
        analysis_id="A1",
        generated_at=300,
        selected_zone_id="SELL_1",
        zones=[sell, buy],
        execution_policy={
            "active_thesis": {
                "locked": True,
                "direction": "BUY",
                "owner_zone_id": "BUY_1",
            },
            "public_zone_map": {
                "secondary": {
                    "sell": {
                        "state": "RESERVE",
                        "execution_authority": False,
                        "source_tf": "H4>H1",
                        "grade": "A+",
                        "low": 4372.59,
                        "high": 4402.59,
                        "core_low": 4392.49,
                        "core_high": 4402.49,
                        "touches": 0,
                        "source_ts": 400,
                    },
                    "buy": None,
                }
            },
        },
    )

    d = _kv(mt5_zone_render_text(a))
    assert d["zone_count"] == "3"
    assert d["active_thesis_locked"] == "1"
    assert d["active_thesis_owner_zone_id"] == "BUY_1"

    assert d["zone1_id"] == "SELL_1"
    assert d["zone1_role"] == "PRIMARY"
    assert d["zone1_zone_low"] == "4323.34000"
    assert d["zone1_core_low"] == "4327.52000"
    assert d["zone1_execution_authority"] == "0"

    assert d["zone2_id"] == "BUY_1"
    assert d["zone2_state"] == "WATCH"
    assert d["zone2_active_thesis"] == "1"
    assert d["zone2_execution_authority"] == "1"

    assert d["zone3_role"] == "RESERVE"
    assert d["zone3_direction"] == "SELL"
    assert d["zone3_state"] == "RESERVE"
    assert d["zone3_zone_high"] == "4402.59000"
    assert d["zone3_core_low"] == "4392.49000"


def test_render_feed_empty_without_analysis():
    d = _kv(mt5_zone_render_text(None))
    assert d["zone_count"] == "0"
    assert d["active_thesis_locked"] == "0"
