from __future__ import annotations

from .config import SETTINGS
from .models import Bar, Direction


def _body(bar: Bar) -> float:
    return abs(float(bar.close) - float(bar.open))


def _atr(bars: list[Bar], n: int = 14) -> float:
    if not bars:
        return 0.0
    trs: list[float] = []
    for i, bar in enumerate(bars):
        previous_close = float(bars[i - 1].close) if i else float(bar.close)
        trs.append(max(float(bar.high) - float(bar.low), abs(float(bar.high) - previous_close), abs(float(bar.low) - previous_close)))
    recent = trs[-n:]
    return sum(recent) / max(1, len(recent))


def _close_side(bar: Bar, zone_low: float, zone_high: float) -> str:
    close = float(bar.close)
    if close < float(zone_low):
        return "BELOW"
    if close > float(zone_high):
        return "ABOVE"
    return "INSIDE"


def _body_fraction_beyond(bar: Bar, boundary: float, direction: Direction) -> float:
    body = max(_body(bar), 1e-9)
    top = max(float(bar.open), float(bar.close))
    bottom = min(float(bar.open), float(bar.close))
    if direction == Direction.SELL:
        beyond = max(0.0, top - max(bottom, float(boundary)))
    else:
        beyond = max(0.0, min(top, float(boundary)) - bottom)
    return beyond / body


def _accepted_invalidation(direction: Direction, zone_low: float, zone_high: float, post_source_bars: list[Bar], index: int, atr_history: list[Bar]) -> tuple[bool, str]:
    bar = post_source_bars[index]
    boundary = float(zone_high) if direction == Direction.SELL else float(zone_low)
    atr_value = max(_atr(atr_history), 1e-9)
    beyond = float(bar.close) > boundary if direction == Direction.SELL else float(bar.close) < boundary
    single = beyond and _body_fraction_beyond(bar, boundary, direction) >= SETTINGS.m15_single_accept_body_fraction and _body(bar) >= SETTINGS.m15_single_accept_body_atr * atr_value
    if single:
        return True, "M15_SINGLE_ACCEPTED_BODY"
    if index < 1:
        return False, ""
    previous = post_source_bars[index - 1]
    both_beyond = (float(previous.close) > boundary and float(bar.close) > boundary) if direction == Direction.SELL else (float(previous.close) < boundary and float(bar.close) < boundary)
    double = both_beyond and _body(previous) >= SETTINGS.m15_double_accept_body_atr * atr_value and _body(bar) >= SETTINGS.m15_double_accept_body_atr * atr_value
    return (True, "M15_DOUBLE_ACCEPTED_CLOSE") if double else (False, "")


def audit_directional_mitigations(direction: Direction, core_low: float, core_high: float, zone_low: float, zone_high: float, source_ts: int, bars: list[Bar]) -> dict:
    """Direction-aware Master Sniper mitigation ledger.

    A raw core touch never consumes freshness by itself. A qualified mitigation
    requires the correct approach, a core touch, and then a later M15 bar that
    closes back through the expected envelope side while its full range is clear
    of the core. Same-bar wick rejection is REACTION_PENDING, not mitigation.
    Recontacts before confirmed departure remain one institutional campaign.
    """
    expected_side = "BELOW" if direction == Direction.SELL else "ABOVE"
    distal_side = "ABOVE" if direction == Direction.SELL else "BELOW"
    all_ordered = sorted(bars, key=lambda b: int(b.ts))
    history_start_ts = int(all_ordered[0].ts) if all_ordered else 0
    history_complete = bool(all_ordered and history_start_ts <= int(source_ts))
    ordered = [bar for bar in all_ordered if int(bar.ts) >= int(source_ts)]

    def result(qualified: int = 0, raw: int = 0, events=None, raw_contacts=None, invalidated_at: int = 0, invalidation_reason: str = "") -> dict:
        return {
            "qualified_mitigations": qualified,
            "raw_core_contact_episodes_before_invalidation": raw,
            "history_complete": history_complete,
            "history_start_ts": history_start_ts,
            "history_required_from_ts": int(source_ts),
            "history_gap_reason": "" if history_complete else "M15_HISTORY_STARTS_AFTER_SOURCE_READY",
            "events": events or [],
            "raw_contacts": raw_contacts or [],
            "invalidated_at": invalidated_at,
            "invalidation_reason": invalidation_reason,
            "expected_approach_side": expected_side,
            "expected_reaction_exit_side": expected_side,
            "distal_invalidation_side": distal_side,
            "counting_stopped": bool(invalidated_at),
            "confirmation_rule": "SUBSEQUENT_M15_EXPECTED_SIDE_CLOSE_CLEAR_OF_CORE",
        }

    if not ordered:
        return result()

    absolute_index = {int(bar.ts): i for i, bar in enumerate(all_ordered)}
    qualified = 0
    raw_core_contacts = 0
    raw_core_engaged = False
    events: list[dict] = []
    raw_contacts: list[dict] = []
    last_outside_side = ""
    last_outside_ts = 0
    campaign: dict | None = None
    reset_required = False

    for index, bar in enumerate(ordered):
        ts = int(bar.ts)
        previous_bar = ordered[index - 1] if index > 0 else None
        abs_index = absolute_index.get(ts, len(all_ordered) - 1)
        invalidated, reason = _accepted_invalidation(direction, zone_low, zone_high, ordered, index, all_ordered[: abs_index + 1])
        close_side = _close_side(bar, zone_low, zone_high)
        hit_core = float(bar.high) >= float(core_low) and float(bar.low) <= float(core_high)

        if invalidated:
            if campaign is not None:
                events.append({**campaign, "event_type": "INTERACTION", "qualified": False, "qualified_index": 0, "qualified_count_before": qualified, "qualified_at": 0, "reason": "INVALIDATED_BEFORE_CONFIRMED_DEPARTURE", "close_side": close_side})
            events.append({"event_type": "INVALIDATION", "qualified": False, "qualified_index": 0, "qualified_count_before": qualified, "armed_at": last_outside_ts, "approach_side": last_outside_side or "UNARMED", "core_touched_at": 0, "qualified_at": 0, "bar_ts": ts, "bar_open": float(bar.open), "bar_high": float(bar.high), "bar_low": float(bar.low), "bar_close": float(bar.close), "close_side": close_side, "reason": reason})
            return result(qualified, raw_core_contacts, events, raw_contacts, ts, reason)

        if hit_core and not raw_core_engaged:
            raw_core_contacts += 1
            raw_core_engaged = True
            immediate_side = "UNAVAILABLE"
            immediate_ts = 0
            if previous_bar is not None:
                immediate_ts = int(previous_bar.ts)
                if float(previous_bar.low) > float(core_high):
                    immediate_side = "ABOVE_CORE"
                elif float(previous_bar.high) < float(core_low):
                    immediate_side = "BELOW_CORE"
                else:
                    immediate_side = "CORE_ADJACENT_OR_OVERLAP"
            raw_contacts.append({
                "raw_contact_index": raw_core_contacts,
                "armed_at": int(last_outside_ts or 0),
                "campaign_approach_side": (campaign or {}).get("approach_side") or last_outside_side or "UNARMED",
                "approach_side": (campaign or {}).get("approach_side") or last_outside_side or "UNARMED",
                "immediate_approach_side": immediate_side,
                "immediate_approach_ts": immediate_ts,
                "core_touched_at": ts,
                "touch_bar_open": float(bar.open), "touch_bar_high": float(bar.high), "touch_bar_low": float(bar.low), "touch_bar_close": float(bar.close),
                "close_side": close_side,
                "contact_role": "RECONTACT_WITHIN_OPEN_CAMPAIGN" if campaign is not None or reset_required else "NEW_CORE_CONTACT_EPISODE",
                "counts_freshness_by_itself": False,
            })
        elif not hit_core:
            raw_core_engaged = False

        if campaign is not None:
            touched_at = int(campaign.get("core_touched_at") or 0)
            # Institutional mitigation is confirmed only after price has fully
            # disengaged from the core on a later M15 bar. A bar that closes on
            # the expected side but still wicks into the core is a recontact in
            # the same campaign, not a completed mitigation.
            if ts > touched_at and close_side == expected_side and not hit_core:
                qualified += 1
                events.append({**campaign, "event_type": "MITIGATION", "qualified": True, "qualified_index": qualified, "qualified_count_before": qualified - 1, "qualified_at": ts, "exit_side": expected_side, "exit_close": float(bar.close), "reason": "CONFIRMED_DIRECTIONAL_CORE_REACTION_COMPLETE"})
                campaign = None
                reset_required = True
            elif close_side == distal_side:
                events.append({**campaign, "event_type": "INTERACTION", "qualified": False, "qualified_index": 0, "qualified_count_before": qualified, "qualified_at": 0, "exit_side": distal_side, "exit_close": float(bar.close), "reason": "WRONG_SIDE_CLOSE_AFTER_CORE_TOUCH"})
                campaign = None
                reset_required = True

        if reset_required and campaign is None and close_side == expected_side and not hit_core:
            reset_required = False
            last_outside_side = expected_side
            last_outside_ts = ts
            continue

        if campaign is None and hit_core and not reset_required:
            approach_side = last_outside_side or "UNARMED"
            touch_reference = float(core_low) if direction == Direction.SELL else float(core_high)
            base = {"armed_at": int(last_outside_ts or 0), "approach_side": approach_side, "core_touched_at": ts, "touch_reference_price": touch_reference, "touch_bar_open": float(bar.open), "touch_bar_high": float(bar.high), "touch_bar_low": float(bar.low), "touch_bar_close": float(bar.close)}
            if approach_side == expected_side:
                campaign = base
                if close_side == expected_side:
                    campaign["touch_rejection_state"] = "REACTION_PENDING_CONFIRMATION"
                elif close_side == distal_side:
                    events.append({**base, "event_type": "INTERACTION", "qualified": False, "qualified_index": 0, "qualified_count_before": qualified, "qualified_at": 0, "exit_side": distal_side, "exit_close": float(bar.close), "reason": "WRONG_SIDE_CLOSE_AFTER_CORE_TOUCH"})
                    campaign = None
                    reset_required = True
            else:
                events.append({**base, "event_type": "INTERACTION", "qualified": False, "qualified_index": 0, "qualified_count_before": qualified, "qualified_at": 0, "reason": "WRONG_APPROACH_SIDE" if approach_side in {"ABOVE", "BELOW"} else "NO_EXPECTED_SIDE_ARM"})
                reset_required = True

        if campaign is None and not reset_required and close_side in {"ABOVE", "BELOW"} and not hit_core:
            last_outside_side = close_side
            last_outside_ts = ts

    if campaign is not None:
        events.append({**campaign, "event_type": "INTERACTION", "qualified": False, "qualified_index": 0, "qualified_count_before": qualified, "qualified_at": 0, "reason": "REACTION_PENDING_CONFIRMATION"})

    return result(qualified, raw_core_contacts, events, raw_contacts)
