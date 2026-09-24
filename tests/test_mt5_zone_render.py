from types import SimpleNamespace

from app.mt5_zone_render import mt5_zone_render_text
import app.thesis_ownership_policy as ownership


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


def _zone(zid, direction, low, high, core_low, core_high, method, grade, source_tf, source_ts, touches, notes=None):
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
        notes=list(notes or []),
    )


def test_render_feed_contains_primary_core_envelope_and_active_thesis(monkeypatch):
    buy = _zone("BUY_1", "BUY", 4248.57, 4288.57, 4253.57, 4270.98, "WATCH|PROMPT", "B+", "H4>H1", 100, 2)
    sell = _zone("SELL_1", "SELL", 4323.34, 4360.40, 4327.52, 4337.52, "ARMED|PROMPT", "A", "H1", 200, 1)
    monkeypatch.setattr(
        ownership,
        "active_owner_snapshot",
        lambda now: {
            "reaction_key": "BUY|H4>H1|100",
            "latest_zone_id": "BUY_1",
            "ownership_zone_id": "BUY_1",
            "direction": "BUY",
            "source_tf": "H4>H1",
            "source_ts": 100,
            "status": "OBJECTIVE_IN_PROGRESS",
            "ownership_acquired_at": 250,
            "ownership_authority": "HTF_CORE_HANDOFF",
            "ownership_analysis_id": "A0",
            "ownership_anchor_price": 4270.0,
            "target1": 4290.0,
            "target2": 4310.0,
            "target3": 4330.0,
            "best_price": 4305.0,
            "mfe_price": 35.0,
            "target1_hit_at": 280,
            "target2_hit_at": 0,
            "target3_hit_at": 0,
            "objective_complete_at": 0,
            "invalidated_at": 0,
            "last_reason": "LIQUIDITY_OBJECTIVE_PROGRESS",
        },
    )
    a = SimpleNamespace(
        analysis_id="A1",
        generated_at=300,
        selected_zone_id="SELL_1",
        zones=[sell, buy],
        execution_policy={
            "active_thesis": {
                "locked": True,
                "direction": "BUY",
                "status": "OBJECTIVE_IN_PROGRESS",
                "owner_zone_id": "BUY_1",
                "owner_zone_present": True,
                "opposite_execution_blocked": True,
                "no_chase": True,
                "fresh_m1_confirmation_required": True,
                "best_price": 4305.0,
                "target1": 4290.0,
                "target2": 4310.0,
                "target3": 4330.0,
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
    assert d["protocol"] == "2"
    assert d["zone_count"] == "3"
    assert d["active_thesis_locked"] == "1"
    assert d["active_thesis_owner_zone_id"] == "BUY_1"
    assert d["active_thesis_status"] == "OBJECTIVE_IN_PROGRESS"
    assert d["active_thesis_opposite_execution_blocked"] == "1"
    assert d["active_thesis_no_chase"] == "1"
    assert d["active_thesis_next_objective"] == "4310.00000"

    assert d["zone1_id"] == "SELL_1"
    assert d["zone1_role"] == "PRIMARY"
    assert d["zone1_zone_low"] == "4323.34000"
    assert d["zone1_core_low"] == "4327.52000"
    assert d["zone1_execution_authority"] == "0"
    assert d["zone1_published_at"] == "300"

    assert d["zone2_id"] == "BUY_1"
    assert d["zone2_state"] == "WATCH"
    assert d["zone2_active_thesis"] == "1"
    assert d["zone2_execution_authority"] == "1"

    assert d["zone3_role"] == "RESERVE"
    assert d["zone3_direction"] == "SELL"
    assert d["zone3_state"] == "RESERVE"
    assert d["zone3_zone_high"] == "4402.59000"
    assert d["zone3_core_low"] == "4392.49000"
    assert d["zone3_published_at"] == "300"


def test_next_objective_uses_best_price_for_sell_progress(monkeypatch):
    sell = _zone("SELL_1", "SELL", 4346.88, 4368.28, 4359.54, 4368.28, "ARMED|PROMPT", "A+", "H4>H1", 100, 0)
    monkeypatch.setattr(
        ownership,
        "active_owner_snapshot",
        lambda now: {
            "reaction_key": "SELL|H4>H1|100",
            "latest_zone_id": "SELL_1",
            "ownership_zone_id": "SELL_1",
            "direction": "SELL",
            "source_tf": "H4>H1",
            "source_ts": 100,
            "status": "OBJECTIVE_IN_PROGRESS",
            "ownership_acquired_at": 250,
            "ownership_authority": "HTF_CORE_HANDOFF",
            "ownership_analysis_id": "A2",
            "ownership_anchor_price": 4360.0,
            "target1": 4341.13,
            "target2": 4324.68,
            "target3": 4299.37,
            "best_price": 4305.0,
            "mfe_price": 55.0,
            "target1_hit_at": 260,
            "target2_hit_at": 280,
            "target3_hit_at": 0,
            "objective_complete_at": 0,
            "invalidated_at": 0,
            "last_reason": "LIQUIDITY_OBJECTIVE_PROGRESS",
        },
    )
    a = SimpleNamespace(
        analysis_id="A2",
        generated_at=300,
        selected_zone_id="SELL_1",
        zones=[sell],
        execution_policy={
            "active_thesis": {
                "locked": True,
                "direction": "SELL",
                "status": "OBJECTIVE_IN_PROGRESS",
                "owner_zone_id": "SELL_1",
                "best_price": 4305.0,
                "target1": 4341.13,
                "target2": 4324.68,
                "target3": 4299.37,
            }
        },
    )
    d = _kv(mt5_zone_render_text(a))
    assert d["active_thesis_next_objective"] == "4299.37000"


def test_render_feed_empty_without_analysis():
    d = _kv(mt5_zone_render_text(None))
    assert d["protocol"] == "2"
    assert d["zone_count"] == "0"
    assert d["active_thesis_locked"] == "0"
    assert d["active_thesis_next_objective"] == "0.00000"


def test_render_feed_uses_exact_geometry_publication_not_source_time():
    sell = _zone(
        "SELL_PUB",
        "SELL",
        4302.19,
        4324.19,
        4303.77,
        4309.77,
        "ARMED|PROMPT",
        "A",
        "H1",
        1_790_190_000,
        0,
        notes=["geometry_published_at:1790210000"],
    )
    a = SimpleNamespace(
        analysis_id="A_PUB",
        generated_at=1_790_220_000,
        selected_zone_id="SELL_PUB",
        zones=[sell],
        execution_policy={"active_thesis": {"locked": False}},
    )
    d = _kv(mt5_zone_render_text(a))
    assert d["zone1_source_ts"] == "1790190000"
    assert d["zone1_published_at"] == "1790210000"
    assert int(d["zone1_published_at"]) > int(d["zone1_source_ts"])


def test_live_renderer_hides_context_buy_once_price_is_below_zone():
    sell = _zone(
        "PZ_H1_SELL_16", "SELL",
        4302.19, 4324.19, 4303.77, 4309.77,
        "ARMED|PROMPT", "A", "H1", 200, 0,
    )
    buy = _zone(
        "PZ_H1_BUY_7", "BUY",
        4256.34, 4272.20, 4261.55, 4267.55,
        "WATCH|PROMPT", "B+", "H1", 100, 4,
    )
    a = SimpleNamespace(
        analysis_id="A_LIVE_SIDE",
        generated_at=300,
        selected_zone_id="PZ_H1_SELL_16",
        zones=[sell, buy],
        execution_policy={"active_thesis": {"locked": False}},
    )

    d = _kv(mt5_zone_render_text(a, current_mid=4255.33))
    assert d["live_mid"] == "4255.33000"
    assert d["wrong_side_hidden_count"] == "1"
    assert d["wrong_side_hidden_ids"] == "PZ_H1_BUY_7"
    assert d["zone_count"] == "1"
    assert d["zone1_id"] == "PZ_H1_SELL_16"


def test_live_renderer_keeps_active_owner_even_if_price_has_moved_beyond_origin_zone():
    buy = _zone(
        "BUY_OWNER", "BUY",
        4256.34, 4272.20, 4261.55, 4267.55,
        "M1_READY|PROMPT", "A+", "H4>H1", 100, 0,
    )
    a = SimpleNamespace(
        analysis_id="A_OWNER_SIDE",
        generated_at=300,
        selected_zone_id="BUY_OWNER",
        zones=[buy],
        execution_policy={
            "active_thesis": {
                "locked": True,
                "direction": "BUY",
                "status": "REACTION_CONFIRMED",
                "owner_zone_id": "BUY_OWNER",
            }
        },
    )

    d = _kv(mt5_zone_render_text(a, current_mid=4250.00))
    assert d["wrong_side_hidden_count"] == "0"
    assert d["zone_count"] == "1"
    assert d["zone1_id"] == "BUY_OWNER"
    assert d["zone1_active_thesis"] == "1"
