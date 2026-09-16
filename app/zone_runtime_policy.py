from __future__ import annotations

import re

from .engine import atr
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone

# XAUUSD convention used by Trade Zone:
# 1 pip = 10 broker points. On the current Deriv XAU feed point=0.01,
# therefore 1 pip = 0.10 in price.
XAU_POINTS_PER_PIP = 10.0

# PAPER/DEMO professional zone geometry, contract V659.
# H4>H1 uses the H1-refined tactical core inside the H4 structural envelope.
H1_CORE_MIN_PIPS = 60.0
H1_CORE_MAX_PIPS = 100.0
H1_ENVELOPE_MIN_PIPS = 140.0
H1_ENVELOPE_MAX_PIPS = 220.0

H4_CORE_MIN_PIPS = 80.0
H4_CORE_MAX_PIPS = 140.0
H4_ENVELOPE_MIN_PIPS = 180.0
H4_ENVELOPE_MAX_PIPS = 260.0

H4H1_CORE_MIN_PIPS = 60.0
H4H1_CORE_MAX_PIPS = 100.0
H4H1_ENVELOPE_MIN_PIPS = 180.0
H4H1_ENVELOPE_MAX_PIPS = 260.0

MIN_SWEEP_ROOM_PIPS = 50.0
MIN_SWEEP_ROOM_POINTS = MIN_SWEEP_ROOM_PIPS * XAU_POINTS_PER_PIP

# Compatibility aliases expose the global outer limits only. Actual qualification
# is source-timeframe-specific through _geometry_pips().
CORE_MIN_PIPS = min(H1_CORE_MIN_PIPS, H4_CORE_MIN_PIPS, H4H1_CORE_MIN_PIPS)
CORE_MAX_PIPS = max(H1_CORE_MAX_PIPS, H4_CORE_MAX_PIPS, H4H1_CORE_MAX_PIPS)
ENVELOPE_MIN_PIPS = min(H1_ENVELOPE_MIN_PIPS, H4_ENVELOPE_MIN_PIPS, H4H1_ENVELOPE_MIN_PIPS)
ENVELOPE_MAX_PIPS = max(H1_ENVELOPE_MAX_PIPS, H4_ENVELOPE_MAX_PIPS, H4H1_ENVELOPE_MAX_PIPS)

CORE_MIN_POINTS = CORE_MIN_PIPS * XAU_POINTS_PER_PIP
CORE_MAX_POINTS = CORE_MAX_PIPS * XAU_POINTS_PER_PIP
ENVELOPE_MIN_POINTS = ENVELOPE_MIN_PIPS * XAU_POINTS_PER_PIP
ENVELOPE_MAX_POINTS = ENVELOPE_MAX_PIPS * XAU_POINTS_PER_PIP

PROMPT_ZONE_CONTRACT = "ZONE_FORMATION_PROMPT_2026_09_14_V659"


def _geometry_pips(source_tf: str) -> dict[str, float]:
    tf = str(source_tf or "").upper()
    if tf == "H4>H1":
        return {
            "core_min": H4H1_CORE_MIN_PIPS,
            "core_max": H4H1_CORE_MAX_PIPS,
            "envelope_min": H4H1_ENVELOPE_MIN_PIPS,
            "envelope_max": H4H1_ENVELOPE_MAX_PIPS,
        }
    if tf == "H4":
        return {
            "core_min": H4_CORE_MIN_PIPS,
            "core_max": H4_CORE_MAX_PIPS,
            "envelope_min": H4_ENVELOPE_MIN_PIPS,
            "envelope_max": H4_ENVELOPE_MAX_PIPS,
        }
    return {
        "core_min": H1_CORE_MIN_PIPS,
        "core_max": H1_CORE_MAX_PIPS,
        "envelope_min": H1_ENVELOPE_MIN_PIPS,
        "envelope_max": H1_ENVELOPE_MAX_PIPS,
    }


def _geometry_points(source_tf: str) -> dict[str, float]:
    p = _geometry_pips(source_tf)
    return {k: float(v) * XAU_POINTS_PER_PIP for k, v in p.items()}


def install_zone_geometry_policy() -> None:
    """Install source-timeframe professional PAPER/DEMO XAU zone geometry.

    The deterministic H4/H1 source detector, structural BSL/SSL requirement,
    M15 invalidation and M1 confirmation remain unchanged. This policy only
    controls core/envelope width and keeps at least 50 XAU pips of distal sweep
    room beyond the attached structural liquidity inside the final envelope.
    """
    from . import institutional_two_zone as zoning

    # Broad compatibility limits for metadata/fallback code. Qualification uses
    # the source-specific functions installed below.
    zoning.CORE_MIN_POINTS = CORE_MIN_POINTS
    zoning.CORE_MAX_POINTS = CORE_MAX_POINTS
    zoning.ENVELOPE_MIN_POINTS = ENVELOPE_MIN_POINTS
    zoning.ENVELOPE_MAX_POINTS = ENVELOPE_MAX_POINTS
    zoning.MIN_SWEEP_ROOM_POINTS = MIN_SWEEP_ROOM_POINTS

    def normalize_core(candidate, snapshot):
        contract = _geometry_points(candidate.source_tf)
        point = zoning._point(snapshot)
        minimum = contract["core_min"] * point
        maximum = contract["core_max"] * point
        lo, hi = sorted((float(candidate.core_low), float(candidate.core_high)))
        width = min(max(max(0.0, hi - lo), minimum), maximum)
        if candidate.direction == Direction.SELL:
            return hi - width, hi
        return lo, lo + width

    def select_liquidity(candidate, core_low, core_high, liq, snapshot):
        required = zoning._required_liquidity(candidate.direction)
        contract = _geometry_points(candidate.source_tf)
        point = zoning._point(snapshot)
        maximum = contract["envelope_max"] * point
        sweep_room = MIN_SWEEP_ROOM_POINTS * point
        source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
        tf_rank = {"D1": 0, "H4": 1, "H1": 2}
        options = []

        for level in liq:
            if required not in str(level.label).upper():
                continue
            tf = str(level.source_tf).upper()
            if tf not in {"D1", "H4", "H1"}:
                continue
            price = float(level.price)
            if candidate.direction == Direction.SELL:
                if price < core_low:
                    continue
                hard_high = max(core_high, price + sweep_room)
                if hard_high - core_low > maximum + 1e-9:
                    continue
                edge_distance = abs(price - core_high)
            else:
                if price > core_high:
                    continue
                hard_low = min(core_low, price - sweep_room)
                if core_high - hard_low > maximum + 1e-9:
                    continue
                edge_distance = abs(core_low - price)
            already_in_source = source_low <= price <= source_high
            options.append((0 if already_in_source else 1, tf_rank.get(tf, 9), edge_distance, float(level.distance), level))

        if not options:
            return None
        options.sort(key=lambda row: row[:-1])
        return options[0][-1]

    def build_geometry(candidate, core_low, core_high, level, snapshot):
        contract = _geometry_points(candidate.source_tf)
        point = zoning._point(snapshot)
        minimum = contract["envelope_min"] * point
        maximum = contract["envelope_max"] * point
        sweep_room = MIN_SWEEP_ROOM_POINTS * point
        source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
        liquidity_price = float(level.price)

        if candidate.direction == Direction.SELL:
            hard_high = max(core_high, liquidity_price + sweep_room)
            if hard_high - core_low > maximum + 1e-9:
                return None
            high = min(max(source_high, hard_high), core_low + maximum)
            low = min(source_low, core_low)
            if high - low > maximum:
                low = high - maximum
            if high - low < minimum:
                low = high - minimum
            if low > core_low + 1e-9 or high < hard_high - 1e-9:
                return None
            actual_room = high - liquidity_price
        else:
            hard_low = min(core_low, liquidity_price - sweep_room)
            if core_high - hard_low > maximum + 1e-9:
                return None
            low = max(min(source_low, hard_low), core_high - maximum)
            high = max(source_high, core_high)
            if high - low > maximum:
                high = low + maximum
            if high - low < minimum:
                high = low + minimum
            if low > hard_low + 1e-9 or high < core_high - 1e-9:
                return None
            actual_room = liquidity_price - low

        width = high - low
        if width < minimum - 1e-9 or width > maximum + 1e-9 or actual_room < sweep_room - 1e-9:
            return None
        return low, high, actual_room

    zoning._normalize_core = normalize_core
    zoning._select_liquidity = select_liquidity
    zoning._build_geometry = build_geometry


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

    contract = _geometry_pips(str(row.get("source_tf") or "H1"))
    row["core_contract_pips"] = [contract["core_min"], contract["core_max"]]
    row["envelope_contract_pips"] = [contract["envelope_min"], contract["envelope_max"]]
    row["minimum_sweep_room_pips"] = MIN_SWEEP_ROOM_PIPS

    reason = str(row.get("rejection_reason") or "")
    reason = reason.replace("200-300 point envelope", "source-timeframe professional envelope")
    reason = reason.replace("200-300 points", "source-timeframe professional envelope")
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
        if not matched and text.startswith("Core is source-anchored"):
            text = (
                "Core/envelope use source-timeframe professional geometry; the required structural liquidity remains "
                "inside the envelope with at least 50 XAU pips of distal sweep room."
            )
        converted.append(text)
    zone.notes = converted
    zone.invalidation_rule = (
        "Closed M15 body acceptance beyond the OUTER professional envelope invalidates the zone. "
        "Wick-only liquidity raids do not invalidate."
    )

    conf = set(zone.confluences)
    conf.discard("CORE_100_150_POINTS")
    conf.discard("ENVELOPE_200_300_POINTS")
    conf.update(
        {
            "PROFESSIONAL_SOURCE_TF_CORE_WIDTH",
            "PROFESSIONAL_SOURCE_TF_ENVELOPE_WIDTH",
            "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM",
        }
    )
    zone.confluences = sorted(conf)
    zone.independent_confluence_count = len(zone.confluences)


def apply_pip_display_contract(analysis: Analysis, snapshot: MarketSnapshot) -> Analysis:
    """Expose source-specific XAU zone geometry in pips while retaining broker-point internals."""
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
            # DataBridge scans literal zone_id keys after zones[]. Removing this
            # duplicate keeps MAP count equal to the real primary zones[] count.
            entry.pop("zone_id", None)
            for old, new in (
                ("core_width_points", "core_width_pips"),
                ("envelope_width_points", "envelope_width_pips"),
                ("sweep_room_points", "sweep_room_pips"),
            ):
                if old in entry:
                    entry[new] = round(_points_to_pips(float(entry[old])), 1)
                    entry.pop(old, None)
            contract = _geometry_pips(str(entry.get("source_tf") or "H1"))
            entry["core_contract_pips"] = [contract["core_min"], contract["core_max"]]
            entry["envelope_contract_pips"] = [contract["envelope_min"], contract["envelope_max"]]
            entry["minimum_sweep_room_pips"] = MIN_SWEEP_ROOM_PIPS
            zone_map[side] = entry

    for key in (
        "core_width_points_min",
        "core_width_points_max",
        "envelope_width_points_min",
        "envelope_width_points_max",
        "min_sweep_room_points",
    ):
        zone_map.pop(key, None)

    diagnostics = zone_map.get("rejected_diagnostics")
    if isinstance(diagnostics, dict):
        for side in ("sell", "buy"):
            info = diagnostics.get(side)
            if isinstance(info, dict):
                _convert_diag_to_pips(info.get("strongest_rejected"))

    geometry_by_tf = {
        "H1": {
            "core_width_pips": [H1_CORE_MIN_PIPS, H1_CORE_MAX_PIPS],
            "envelope_width_pips": [H1_ENVELOPE_MIN_PIPS, H1_ENVELOPE_MAX_PIPS],
        },
        "H4": {
            "core_width_pips": [H4_CORE_MIN_PIPS, H4_CORE_MAX_PIPS],
            "envelope_width_pips": [H4_ENVELOPE_MIN_PIPS, H4_ENVELOPE_MAX_PIPS],
        },
        "H4>H1": {
            "core_width_pips": [H4H1_CORE_MIN_PIPS, H4H1_CORE_MAX_PIPS],
            "envelope_width_pips": [H4H1_ENVELOPE_MIN_PIPS, H4H1_ENVELOPE_MAX_PIPS],
        },
    }

    zone_map["prompt_contract_ref"] = PROMPT_ZONE_CONTRACT
    zone_map["width_display_unit"] = "pips"
    zone_map["xau_points_per_pip"] = XAU_POINTS_PER_PIP
    zone_map["geometry_by_source_tf"] = geometry_by_tf
    zone_map["min_sweep_room_pips"] = MIN_SWEEP_ROOM_PIPS
    zone_map["liquidity_must_be_inside_envelope"] = True
    zone_map["sweep_room_beyond_liquidity_must_be_inside_envelope"] = True
    zone_map["equal_high_low_are_liquidity_objects_only"] = True
    zone_map["equal_high_low_do_not_create_zone_without_institutional_source"] = True
    zone_map["buy_zone_must_be_below_or_interacting"] = True
    zone_map["sell_zone_must_be_above_or_interacting"] = True
    zone_map["wrong_side_zone_is_rejected_not_flipped"] = True
    zone_map["max_primary_per_side"] = 1
    zone_map["max_reserve_per_side"] = 1
    zone_map["reserve_zone_is_not_forced"] = True
    zone_map["reachability_is_ranking_only"] = True
    zone_map["remote_htf_zone_can_remain_context"] = True
    policy["public_zone_map"] = zone_map

    geometry = dict(policy.get("zone_geometry") or {})
    geometry.pop("core_width_points", None)
    geometry.pop("envelope_width_points", None)
    geometry.pop("minimum_sweep_room_points", None)
    geometry["geometry_by_source_tf"] = geometry_by_tf
    geometry["minimum_sweep_room_pips"] = MIN_SWEEP_ROOM_PIPS
    geometry["display_unit"] = "pips"
    geometry["xau_points_per_pip"] = XAU_POINTS_PER_PIP
    geometry["liquidity_must_be_inside_envelope"] = True
    geometry["equal_high_low_role"] = "LIQUIDITY_ONLY_NOT_ZONE_SOURCE"
    policy["zone_geometry"] = geometry

    primary = list(policy.get("primary") or [])
    replacements = {
        "CORE_100_150_POINTS": "PROFESSIONAL_SOURCE_TF_CORE_WIDTH",
        "ENVELOPE_200_300_POINTS": "PROFESSIONAL_SOURCE_TF_ENVELOPE_WIDTH",
        "MINIMUM_50_POINT_DISTAL_SWEEP_ROOM": "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM",
    }
    primary = [replacements.get(x, x) for x in primary]
    for rule in (
        "BUY_BELOW_OR_INTERACTING_WITH_CURRENT_PRICE",
        "SELL_ABOVE_OR_INTERACTING_WITH_CURRENT_PRICE",
        "NO_FORCED_SECOND_ZONE",
        "INTRADAY_REACHABILITY_RANKS_VALID_ZONES_ONLY",
        "EQH_EQL_ARE_LIQUIDITY_ONLY_NOT_ZONE_SOURCES",
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
    brief = brief.replace(
        "Core width is 100-150 points. Outer envelope is 200-300 points.",
        "Professional source-TF geometry: H1 core 60-100 pips / envelope 140-220 pips; H4 core 80-140 pips / envelope 180-260 pips; H4>H1 uses an H1-refined 60-100 pip core inside an H4 180-260 pip envelope.",
    )
    brief = brief.replace("at least 50 points reserved", "at least 50 pips reserved")
    brief += (
        " Equal highs/lows remain liquidity objects only; they never manufacture a zone without a valid H4/H1 institutional source."
        " Prompt alert-side rule: BUY must be below current price or already interacting; "
        "SELL must be above current price or already interacting. No second zone is forced. "
        "At most one Primary and one non-executable Reserve may be shown per side when both independently qualify. "
        "Among structurally valid same-side zones, intraday reachability ranks today's alert while remote HTF zones remain context."
    )
    analysis.trader_brief = brief
    return analysis
