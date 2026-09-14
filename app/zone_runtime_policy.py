from __future__ import annotations

import re

from .engine import atr
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone

# XAUUSD convention used by Trade Zone:
# 1 pip = 10 broker points. On the current Deriv XAU feed point=0.01,
# therefore 1 pip = 0.10 in price.
XAU_POINTS_PER_PIP = 10.0

# PAPER/DEMO zone geometry requested for v6.5.2 and retained in v6.5.3.
CORE_MIN_PIPS = 100.0
CORE_MAX_PIPS = 200.0
ENVELOPE_MIN_PIPS = 300.0
ENVELOPE_MAX_PIPS = 400.0
MIN_SWEEP_ROOM_PIPS = 50.0

CORE_MIN_POINTS = CORE_MIN_PIPS * XAU_POINTS_PER_PIP
CORE_MAX_POINTS = CORE_MAX_PIPS * XAU_POINTS_PER_PIP
ENVELOPE_MIN_POINTS = ENVELOPE_MIN_PIPS * XAU_POINTS_PER_PIP
ENVELOPE_MAX_POINTS = ENVELOPE_MAX_PIPS * XAU_POINTS_PER_PIP
MIN_SWEEP_ROOM_POINTS = MIN_SWEEP_ROOM_PIPS * XAU_POINTS_PER_PIP

PROMPT_ZONE_CONTRACT = "ZONE_FORMATION_PROMPT_2026_09_14_V653"


def install_zone_geometry_policy() -> None:
    """Install the requested PAPER/DEMO XAU zone widths.

    Candidate source detection, BSL/SSL qualification, M15 invalidation and M1
    confirmation are unchanged. Only the geometry constants are replaced.
    """
    from . import institutional_two_zone as zoning

    zoning.CORE_MIN_POINTS = CORE_MIN_POINTS
    zoning.CORE_MAX_POINTS = CORE_MAX_POINTS
    zoning.ENVELOPE_MIN_POINTS = ENVELOPE_MIN_POINTS
    zoning.ENVELOPE_MAX_POINTS = ENVELOPE_MAX_POINTS
    zoning.MIN_SWEEP_ROOM_POINTS = MIN_SWEEP_ROOM_POINTS


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _points_to_pips(value: float) -> float:
    return float(value) / XAU_POINTS_PER_PIP


def _price_to_pips(distance: float, snapshot: MarketSnapshot) -> float:
    point = max(abs(float(snapshot.point or 0.01)), 1e-9)
    return float(distance) / point / XAU_POINTS_PER_PIP


def _market_side_rejection(direction: Direction, low: float, high: float, mid: float) -> tuple[str, str]:
    """Apply the prompt's intraday alert-location rule.

    BUY demand must be below current price or already interacting with current
    price. SELL supply must be above current price or already interacting with
    current price. A wrong-side zone is not automatically flipped.
    """
    lo, hi = sorted((float(low), float(high)))
    price = float(mid)
    if direction == Direction.BUY and lo > price:
        return (
            "BUY_ZONE_ABOVE_CURRENT_PRICE",
            "BUY alert zone is completely above current price. The prompt requires BUY demand below price or current price already interacting with the zone.",
        )
    if direction == Direction.SELL and hi < price:
        return (
            "SELL_ZONE_BELOW_CURRENT_PRICE",
            "SELL alert zone is completely below current price. The prompt requires SELL supply above price or current price already interacting with the zone.",
        )
    return "", ""


def install_prompt_market_side_policy() -> None:
    """Reject wrong-side alert zones before one-per-side selection.

    This wrapper changes only PAPER/DEMO zone publication. It does not create a
    trade, flip a zone, alter M1 confirmation, lot size, stops or risk logic.
    """
    from . import institutional_two_zone as zoning

    current = zoning._candidate_zone
    if getattr(current, "_prompt_market_side_policy", False):
        return

    def wrapped(candidate, snapshot, liq, context, index):
        zone, diag = current(candidate, snapshot, liq, context, index)
        if zone is None:
            return zone, diag
        code, reason = _market_side_rejection(
            zone.original_direction,
            float(zone.zone_low),
            float(zone.zone_high),
            float(snapshot.mid),
        )
        if not code:
            return zone, diag
        out = dict(diag or {})
        out.update(
            {
                "current_price": round(float(snapshot.mid), 5),
                "rejection_code": code,
                "rejection_reason": reason,
            }
        )
        return None, out

    wrapped._prompt_market_side_policy = True
    zoning._candidate_zone = wrapped


def _reachability_bucket(zone: Zone, snapshot: MarketSnapshot) -> tuple[int, float]:
    """Ranking only. Never creates or qualifies a zone."""
    h1a = max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9)
    distance = _distance(float(snapshot.mid), float(zone.zone_low), float(zone.zone_high))
    distance_atr = distance / h1a
    if distance_atr <= 1.5:
        bucket = 0
    elif distance_atr <= 3.0:
        bucket = 1
    elif distance_atr <= 5.0:
        bucket = 2
    else:
        bucket = 3
    return bucket, distance_atr


def intraday_zone_rank(zone: Zone, snapshot: MarketSnapshot) -> tuple:
    """Choose the strongest valid location most likely to matter today.

    Structural qualification happens before this rank. Among already-valid
    zones, freshness and intraday reachability come before remote HTF authority.
    A remote HTF source can remain context, but it should not automatically beat
    a much nearer equally-executable institutional alert zone.
    """
    execution_grade_tier = 0 if zone.grade in {Grade.A_PLUS, Grade.A} else 1
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 9}.get(zone.grade, 9)
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(str(zone.source_tf), 9)
    reach_bucket, distance_atr = _reachability_bucket(zone, snapshot)
    return (
        execution_grade_tier,
        int(zone.touch_count),
        reach_bucket,
        grade_rank,
        tf_rank,
        0 if "HISTORICAL_DISPLACEMENT_FVG" in set(zone.confluences) else 1,
        0 if "TICK_VOLUME_EXPANSION" in set(zone.confluences) else 1,
        -float(zone.location_score),
        distance_atr,
        -int(zone.source_ts),
    )


def install_zone_rank_policy() -> None:
    """Install prompt-guided intraday ranking; qualification remains separate."""
    from . import institutional_two_zone as zoning

    zoning._rank = intraday_zone_rank


def _convert_diag_to_pips(row: dict | None) -> None:
    if not isinstance(row, dict):
        return
    for old, new in (
        ("core_width_points", "core_width_pips"),
        ("envelope_width_points", "envelope_width_pips"),
        ("sweep_room_points", "sweep_room_pips"),
    ):
        if old in row:
            try:
                row[new] = round(_points_to_pips(float(row[old])), 1)
            except (TypeError, ValueError):
                row[new] = row[old]
            row.pop(old, None)

    reason = str(row.get("rejection_reason") or "")
    # The underlying zoning module still contains legacy wording; normalize the
    # user-facing explanation to the active v6.5.2+ pip contract.
    reason = reason.replace("200-300 point envelope", "300-400 pip envelope")
    reason = reason.replace("200-300 points", "300-400 pips")
    reason = reason.replace("50 points", "50 pips")
    row["rejection_reason"] = reason


def _convert_zone_notes(zone: Zone) -> None:
    converted: list[str] = []
    for raw in zone.notes:
        text = str(raw)
        matched = False
        for old, new in (
            ("core_width_points:", "core_width_pips:"),
            ("envelope_width_points:", "envelope_width_pips:"),
            ("sweep_room_points:", "sweep_room_pips:"),
        ):
            if text.startswith(old):
                try:
                    value = float(text.split(":", 1)[1])
                    text = f"{new}{_points_to_pips(value):.1f}"
                except (TypeError, ValueError):
                    pass
                matched = True
                break
        if not matched:
            text = text.replace("100-150 points", "100-200 pips")
            text = text.replace("200-300 points", "300-400 pips")
            text = text.replace("50 points", "50 pips")
        converted.append(text)
    zone.notes = converted
    zone.invalidation_rule = str(zone.invalidation_rule).replace(
        "200-300 point envelope", "300-400 pip envelope"
    )


def apply_pip_display_contract(analysis: Analysis, snapshot: MarketSnapshot) -> Analysis:
    """Expose all XAU zone widths in pips while retaining broker-point internals."""
    if analysis is None:
        return analysis

    for zone in analysis.zones:
        _convert_zone_notes(zone)

    policy = dict(analysis.execution_policy or {})
    zone_map = dict(policy.get("public_zone_map") or {})

    for side in ("sell", "buy"):
        entry = zone_map.get(side)
        if isinstance(entry, dict):
            entry = dict(entry)
            # DataBridge v1.34 scans literal zone_id keys after zones[]. Removing
            # this duplicate keeps MAP count equal to the real zones[] count.
            entry.pop("zone_id", None)
            for old, new in (
                ("core_width_points", "core_width_pips"),
                ("envelope_width_points", "envelope_width_pips"),
                ("sweep_room_points", "sweep_room_pips"),
            ):
                if old in entry:
                    entry[new] = round(_points_to_pips(float(entry[old])), 1)
                    entry.pop(old, None)
            zone_map[side] = entry

    for old, new in (
        ("core_width_points_min", "core_width_pips_min"),
        ("core_width_points_max", "core_width_pips_max"),
        ("envelope_width_points_min", "envelope_width_pips_min"),
        ("envelope_width_points_max", "envelope_width_pips_max"),
        ("min_sweep_room_points", "min_sweep_room_pips"),
    ):
        if old in zone_map:
            zone_map[new] = round(_points_to_pips(float(zone_map[old])), 1)
            zone_map.pop(old, None)

    diagnostics = zone_map.get("rejected_diagnostics")
    if isinstance(diagnostics, dict):
        for side in ("sell", "buy"):
            info = diagnostics.get(side)
            if isinstance(info, dict):
                _convert_diag_to_pips(info.get("strongest_rejected"))

    zone_map["prompt_contract_ref"] = PROMPT_ZONE_CONTRACT
    zone_map["width_display_unit"] = "pips"
    zone_map["xau_points_per_pip"] = XAU_POINTS_PER_PIP
    zone_map["core_width_pips_min"] = CORE_MIN_PIPS
    zone_map["core_width_pips_max"] = CORE_MAX_PIPS
    zone_map["envelope_width_pips_min"] = ENVELOPE_MIN_PIPS
    zone_map["envelope_width_pips_max"] = ENVELOPE_MAX_PIPS
    zone_map["min_sweep_room_pips"] = MIN_SWEEP_ROOM_PIPS
    zone_map["buy_zone_must_be_below_or_interacting"] = True
    zone_map["sell_zone_must_be_above_or_interacting"] = True
    zone_map["wrong_side_zone_is_rejected_not_flipped"] = True
    zone_map["no_forced_second_zone"] = True
    zone_map["reachability_is_ranking_only"] = True
    zone_map["remote_htf_zone_can_remain_context"] = True
    policy["public_zone_map"] = zone_map

    geometry = dict(policy.get("zone_geometry") or {})
    geometry.pop("core_width_points", None)
    geometry.pop("envelope_width_points", None)
    geometry.pop("minimum_sweep_room_points", None)
    geometry["core_width_pips"] = [CORE_MIN_PIPS, CORE_MAX_PIPS]
    geometry["envelope_width_pips"] = [ENVELOPE_MIN_PIPS, ENVELOPE_MAX_PIPS]
    geometry["minimum_sweep_room_pips"] = MIN_SWEEP_ROOM_PIPS
    geometry["display_unit"] = "pips"
    geometry["xau_points_per_pip"] = XAU_POINTS_PER_PIP
    policy["zone_geometry"] = geometry

    primary = list(policy.get("primary") or [])
    replacements = {
        "CORE_100_150_POINTS": "CORE_100_200_PIPS",
        "ENVELOPE_200_300_POINTS": "ENVELOPE_300_400_PIPS",
        "MINIMUM_50_POINT_DISTAL_SWEEP_ROOM": "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM",
    }
    primary = [replacements.get(x, x) for x in primary]
    for rule in (
        "BUY_BELOW_OR_INTERACTING_WITH_CURRENT_PRICE",
        "SELL_ABOVE_OR_INTERACTING_WITH_CURRENT_PRICE",
        "NO_FORCED_SECOND_ZONE",
        "INTRADAY_REACHABILITY_RANKS_VALID_ZONES_ONLY",
    ):
        if rule not in primary:
            primary.append(rule)
    policy["primary"] = primary
    analysis.execution_policy = policy

    brief = str(analysis.trader_brief or "")
    brief = re.sub(
        r"sweep_room=([0-9]+(?:\.[0-9]+)?)pt",
        lambda m: f"sweep_room={float(m.group(1)) / XAU_POINTS_PER_PIP:.1f}pip",
        brief,
    )
    brief = brief.replace("Core width is 100-150 points.", "Core width is 100-200 pips.")
    brief = brief.replace("Outer envelope is 200-300 points.", "Outer envelope is 300-400 pips.")
    brief = brief.replace("at least 50 points reserved", "at least 50 pips reserved")
    brief += (
        " Prompt alert-side rule: BUY must be below current price or already interacting; "
        "SELL must be above current price or already interacting. No second zone is forced. "
        "Among structurally valid same-side zones, intraday reachability ranks today's alert while remote HTF zones remain context."
    )
    analysis.trader_brief = brief
    return analysis
