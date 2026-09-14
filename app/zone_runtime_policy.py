from __future__ import annotations

import re

from .engine import atr
from .models import Analysis, Grade, MarketSnapshot, Zone

# XAUUSD display convention used by Trade Zone:
# 1 pip = 10 broker points. On the current Deriv XAU feed point=0.01,
# therefore 1 pip = 0.10 in price.
XAU_POINTS_PER_PIP = 10.0


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


def _reachability_bucket(zone: Zone, snapshot: MarketSnapshot) -> tuple[int, float]:
    """Ranking only. Never rejects a structurally valid zone."""
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
    """Rank valid zones for today's alert without deleting remote HTF zones.

    A/A+ zones remain the execution-quality tier. Freshness comes next, then an
    intraday reachability bucket, then HTF source authority and finer quality.
    This lets a much closer equally-valid zone outrank a remote context zone,
    while B+ WATCH zones still remain below A/A+ zones.
    """
    execution_grade_tier = 0 if zone.grade in {Grade.A_PLUS, Grade.A} else 1
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 9}.get(zone.grade, 9)
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(str(zone.source_tf), 9)
    reach_bucket, distance_atr = _reachability_bucket(zone, snapshot)
    return (
        execution_grade_tier,
        int(zone.touch_count),
        reach_bucket,
        tf_rank,
        grade_rank,
        0 if "HISTORICAL_DISPLACEMENT_FVG" in set(zone.confluences) else 1,
        0 if "TICK_VOLUME_EXPANSION" in set(zone.confluences) else 1,
        -float(zone.location_score),
        distance_atr,
        -int(zone.source_ts),
    )


def install_zone_rank_policy() -> None:
    """Install ranking only; candidate creation/qualification remains unchanged."""
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
    reason = reason.replace("200-300 point envelope", "20-30 pip envelope")
    reason = reason.replace("200-300 points", "20-30 pips")
    reason = reason.replace("50 points", "5 pips")
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
            text = text.replace("100-150 points", "10-15 pips")
            text = text.replace("200-300 points", "20-30 pips")
            text = text.replace("50 points", "5 pips")
        converted.append(text)
    zone.notes = converted
    zone.invalidation_rule = str(zone.invalidation_rule).replace(
        "200-300 point envelope", "20-30 pip envelope"
    )


def apply_pip_display_contract(analysis: Analysis, snapshot: MarketSnapshot) -> Analysis:
    """Convert user-facing XAU zone width readings from points to pips.

    Geometry itself is unchanged. This also removes duplicated public-map
    ``zone_id`` fields so DataBridge v1.34 counts only actual entries in zones[].
    """
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
            # DataBridge v1.34 scans for the literal key "zone_id" after zones[].
            # Keeping it here can make one zone appear as MAP 2. The canonical ID
            # remains in analysis.zones, so removing this duplicate is safe.
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

    zone_map["width_display_unit"] = "pips"
    zone_map["xau_points_per_pip"] = XAU_POINTS_PER_PIP
    zone_map["reachability_is_ranking_only"] = True
    policy["public_zone_map"] = zone_map

    geometry = dict(policy.get("zone_geometry") or {})
    if "core_width_points" in geometry:
        geometry["core_width_pips"] = [round(_points_to_pips(x), 1) for x in geometry.pop("core_width_points")]
    if "envelope_width_points" in geometry:
        geometry["envelope_width_pips"] = [round(_points_to_pips(x), 1) for x in geometry.pop("envelope_width_points")]
    if "minimum_sweep_room_points" in geometry:
        geometry["minimum_sweep_room_pips"] = round(_points_to_pips(geometry.pop("minimum_sweep_room_points")), 1)
    geometry["display_unit"] = "pips"
    geometry["xau_points_per_pip"] = XAU_POINTS_PER_PIP
    policy["zone_geometry"] = geometry

    primary = list(policy.get("primary") or [])
    replacements = {
        "CORE_100_150_POINTS": "CORE_10_15_PIPS",
        "ENVELOPE_200_300_POINTS": "ENVELOPE_20_30_PIPS",
        "MINIMUM_50_POINT_DISTAL_SWEEP_ROOM": "MINIMUM_5_PIP_DISTAL_SWEEP_ROOM",
    }
    policy["primary"] = [replacements.get(x, x) for x in primary]
    analysis.execution_policy = policy

    brief = str(analysis.trader_brief or "")
    brief = re.sub(
        r"sweep_room=([0-9]+(?:\.[0-9]+)?)pt",
        lambda m: f"sweep_room={float(m.group(1)) / XAU_POINTS_PER_PIP:.1f}pip",
        brief,
    )
    brief = brief.replace("Core width is 100-150 points.", "Core width is 10-15 pips.")
    brief = brief.replace("Outer envelope is 200-300 points.", "Outer envelope is 20-30 pips.")
    brief = brief.replace("at least 50 points reserved", "at least 5 pips reserved")
    analysis.trader_brief = brief
    return analysis
