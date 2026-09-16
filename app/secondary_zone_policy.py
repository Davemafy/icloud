from __future__ import annotations

from .engine import atr
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone

SECONDARY_ZONE_CONTRACT = "ZONE_FORMATION_PROMPT_2026_09_14_V659_SECONDARY_RESERVE"
XAU_POINTS_PER_PIP = 10.0
MAX_RESERVE_TOUCHES = 1
RESERVE_GRADES = {Grade.A_PLUS, Grade.A}


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _same_source(a: Zone, b: Zone) -> bool:
    if int(a.source_ts) == int(b.source_ts) and str(a.source_tf) == str(b.source_tf):
        return True
    return (
        abs(float(a.core_low) - float(b.core_low)) <= 1e-9
        and abs(float(a.core_high) - float(b.core_high)) <= 1e-9
    )


def _clean_level_two(primary: Zone, reserve: Zone) -> bool:
    """Level 2 must sit beyond the primary invalidation side and not overlap it."""
    if reserve.original_direction != primary.original_direction:
        return False
    if _same_source(primary, reserve):
        return False
    if reserve.grade not in RESERVE_GRADES:
        return False
    if int(reserve.touch_count) > MAX_RESERVE_TOUCHES:
        return False

    if primary.original_direction == Direction.SELL:
        # If SELL L1 fails by accepted price above its envelope, L2 must be a
        # distinct higher supply zone that has not already been crossed.
        return float(reserve.zone_low) >= float(primary.zone_high)

    # If BUY L1 fails by accepted price below its envelope, L2 must be a
    # distinct lower demand zone that has not already been crossed.
    return float(reserve.zone_high) <= float(primary.zone_low)


def _note_value(zone: Zone, prefix: str) -> float:
    for note in zone.notes:
        text = str(note)
        if text.startswith(prefix):
            try:
                return float(text.split(":", 1)[1])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _price_width_to_pips(width: float, snapshot: MarketSnapshot) -> float:
    point = max(abs(float(snapshot.point or 0.01)), 1e-9)
    return float(width) / point / XAU_POINTS_PER_PIP


def _attached_liquidity(zone: Zone) -> str:
    return next((str(n) for n in zone.notes if str(n).startswith("attached_liquidity:")), "")


def _reserve_payload(primary: Zone, reserve: Zone, snapshot: MarketSnapshot) -> dict:
    h1a = max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9)
    distance_atr = _distance(float(snapshot.mid), float(reserve.zone_low), float(reserve.zone_high)) / h1a
    required = "BSL" if reserve.original_direction == Direction.SELL else "SSL"
    sweep_points = _note_value(reserve, "sweep_room_points:")
    sweep_pips = sweep_points / XAU_POINTS_PER_PIP if sweep_points > 0 else 0.0
    return {
        "state": "RESERVE",
        "execution_authority": False,
        "source_tf": reserve.source_tf,
        "grade": reserve.grade.value,
        "low": reserve.zone_low,
        "high": reserve.zone_high,
        "core_low": reserve.core_low,
        "core_high": reserve.core_high,
        "touches": reserve.touch_count,
        "required_liquidity": required,
        "liquidity_in_zone": "LIQUIDITY_IN_MARKED_ZONE" in set(reserve.confluences),
        "attached_liquidity": _attached_liquidity(reserve),
        "source_ts": reserve.source_ts,
        "invalidation": reserve.invalidation_level,
        "distance_h1_atr": round(distance_atr, 3),
        "core_width_pips": round(_price_width_to_pips(float(reserve.core_high) - float(reserve.core_low), snapshot), 1),
        "envelope_width_pips": round(_price_width_to_pips(float(reserve.zone_high) - float(reserve.zone_low), snapshot), 1),
        "sweep_room_pips": round(sweep_pips, 1),
        "primary_invalidation_trigger": primary.invalidation_level,
        "promotion_rule": "PRIMARY_M15_INVALIDATED_THEN_FRESH_REQUALIFICATION",
        "fresh_requalification_required": True,
        "must_remain_active": True,
        "must_remain_correct_side_of_price": True,
        "must_retain_structural_liquidity": True,
        "m1_handoff_disabled_while_primary_valid": True,
    }


def apply_secondary_zone_policy(analysis: Analysis, snapshot: MarketSnapshot) -> Analysis:
    """Publish one non-executable reserve zone per side behind the primary.

    PAPER/DEMO ONLY. This function does not add the reserve to analysis.zones,
    does not change selected_zone_id, and does not grant M1 execution authority.
    On a later fresh analysis, if the primary has been invalidated by M15 accepted
    price and the reserve still qualifies, normal primary selection can promote it.
    """
    if analysis is None:
        return analysis

    from . import institutional_two_zone as zoning

    candidates = zoning._build_candidates(snapshot)
    accepted: dict[Direction, list[Zone]] = {Direction.SELL: [], Direction.BUY: []}
    for index, candidate in enumerate(candidates, 1):
        zone, _ = zoning._candidate_zone(candidate, snapshot, analysis.liquidity_map, analysis.overall_bias, index)
        if zone is not None and zone.grade in RESERVE_GRADES and int(zone.touch_count) <= MAX_RESERVE_TOUCHES:
            accepted[zone.original_direction].append(zone)

    primary_by_side = {z.original_direction: z for z in analysis.zones}
    reserve_map: dict[str, dict | None] = {"sell": None, "buy": None}
    brief_parts: list[str] = []

    for direction in (Direction.SELL, Direction.BUY):
        primary = primary_by_side.get(direction)
        if primary is None:
            continue

        options = [z for z in accepted[direction] if _clean_level_two(primary, z)]
        if not options:
            continue
        options.sort(key=lambda z: zoning._rank(z, snapshot))
        reserve = options[0]
        payload = _reserve_payload(primary, reserve, snapshot)
        reserve_map[direction.value.lower()] = payload
        brief_parts.append(
            f"{direction.value}2={reserve.zone_low:.2f}-{reserve.zone_high:.2f} "
            f"(core={reserve.core_low:.2f}-{reserve.core_high:.2f},{reserve.source_tf},{reserve.grade.value},RESERVE,touches={reserve.touch_count})"
        )

    policy = dict(analysis.execution_policy or {})
    zone_map = dict(policy.get("public_zone_map") or {})
    zone_map["secondary_zone_contract"] = SECONDARY_ZONE_CONTRACT
    zone_map["secondary_zone_policy"] = {
        "purpose": "BACKUP_LEVEL_AFTER_PRIMARY_INVALIDATION",
        "max_secondary_per_side": 1,
        "secondary_is_context_only": True,
        "secondary_has_no_execution_authority": True,
        "secondary_must_be_distinct_and_non_overlapping": True,
        "sell_secondary_must_be_above_primary": True,
        "buy_secondary_must_be_below_primary": True,
        "primary_m15_invalidation_required_before_promotion": True,
        "fresh_requalification_required_before_promotion": True,
        "m1_confirmation_still_required_after_promotion": True,
        "equal_high_low_cannot_create_reserve_without_institutional_source": True,
    }
    zone_map["secondary"] = reserve_map
    policy["public_zone_map"] = zone_map
    analysis.execution_policy = policy

    if brief_parts:
        analysis.trader_brief += (
            " Secondary reserve map (context only): " + "; ".join(brief_parts)
            + ". Level 2 has no M1 authority while Level 1 is valid. After M15 accepted invalidation of Level 1, a fresh analysis must requalify Level 2 before it can become primary."
        )
    else:
        analysis.trader_brief += (
            " Secondary reserve map: none currently qualifies. No backup level is forced; a reserve must be a separate A/A+ source beyond the primary invalidation side."
        )

    return analysis
