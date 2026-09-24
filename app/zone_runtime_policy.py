from __future__ import annotations

from .engine import atr
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone

# MASTER SNIPER TOTAL AUTHORITY
# A zone must be anchored to a real H4/H1 institutional source, but the tradable
# area is the complete source/liquidity structure.  A source candle is an anchor,
# not a prison: structural BSL/SSL may sit outside that single candle and still be
# part of the same institutional area.  We never manufacture fixed-width or ATR
# padding and never reject a valid structure merely because liquidity is outside
# one source candle.
XAU_POINTS_PER_PIP = 10.0
MIN_SWEEP_ROOM_POINTS = 0.0
MIN_SWEEP_ROOM_PIPS = 0.0
PROMPT_ZONE_CONTRACT = "MASTER_SNIPER_TOTAL_AUTHORITY_V6578"

# Legacy compatibility names. Width contracts do not qualify/manufacture zones.
CORE_MIN_POINTS = 0.0
CORE_MAX_POINTS = 0.0
ENVELOPE_MIN_POINTS = 0.0
ENVELOPE_MAX_POINTS = 0.0
CORE_MIN_PIPS = 0.0
CORE_MAX_PIPS = 0.0
ENVELOPE_MIN_PIPS = 0.0
ENVELOPE_MAX_PIPS = 0.0
H1_CORE_MIN_PIPS = H1_CORE_MAX_PIPS = 0.0
H1_ENVELOPE_MIN_PIPS = H1_ENVELOPE_MAX_PIPS = 0.0
H4_CORE_MIN_PIPS = H4_CORE_MAX_PIPS = 0.0
H4_ENVELOPE_MIN_PIPS = H4_ENVELOPE_MAX_PIPS = 0.0
H4H1_CORE_MIN_PIPS = H4H1_CORE_MAX_PIPS = 0.0
H4H1_ENVELOPE_MIN_PIPS = H4H1_ENVELOPE_MAX_PIPS = 0.0


def _geometry_pips(source_tf: str) -> dict[str, float]:
    return {"core_min": 0.0, "core_max": 0.0, "envelope_min": 0.0, "envelope_max": 0.0}


def _geometry_points(source_tf: str) -> dict[str, float]:
    return {"core_min": 0.0, "core_max": 0.0, "envelope_min": 0.0, "envelope_max": 0.0}


def install_zone_geometry_policy() -> None:
    """Install Master Sniper source-anchored composite zoning into the engine."""
    from . import institutional_two_zone as zoning

    def normalize_core(candidate, snapshot):
        # Native source core only. No arbitrary minimum/maximum width.
        lo, hi = sorted((float(candidate.core_low), float(candidate.core_high)))
        return lo, hi

    def select_liquidity(candidate, core_low, core_high, liq, snapshot):
        required = zoning._required_liquidity(candidate.direction)
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
            # Directional relationship is mandatory. Unlike the old source-exact
            # implementation, the liquidity does NOT have to be inside one candle.
            if candidate.direction == Direction.SELL and price < core_low:
                continue
            if candidate.direction == Direction.BUY and price > core_high:
                continue
            already_in_source = source_low <= price <= source_high
            edge = abs(price - (core_high if candidate.direction == Direction.SELL else core_low))
            # Prefer HTF liquidity, then liquidity naturally inside the source,
            # then the nearest structurally-correct pool. Distance ranks; it does
            # not impose a synthetic width rejection.
            options.append((tf_rank.get(tf, 9), 0 if already_in_source else 1, edge, float(level.distance), level))
        if not options:
            return None
        options.sort(key=lambda row: row[:-1])
        return options[0][-1]

    def build_geometry(candidate, core_low, core_high, level, snapshot):
        source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
        liquidity_price = float(level.price)
        if core_low < source_low - 1e-9 or core_high > source_high + 1e-9:
            return None

        # MASTER SNIPER composite area = real source structure + the structural
        # liquidity pool that gives the setup its purpose. No ATR/fixed-width
        # padding and no artificial clipping. This is the key correction that
        # prevents valid 4275-4290-style areas from being rejected simply because
        # their BSL/SSL is not inside a single source candle.
        low = min(source_low, core_low, liquidity_price)
        high = max(source_high, core_high, liquidity_price)
        if candidate.direction == Direction.SELL:
            distal_room = max(0.0, high - liquidity_price)
        else:
            distal_room = max(0.0, liquidity_price - low)
        return low, high, distal_room

    zoning._normalize_core = normalize_core
    zoning._select_liquidity = select_liquidity
    zoning._build_geometry = build_geometry


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _market_side_rejection(direction: Direction, low: float, high: float, mid: float) -> tuple[str, str]:
    lo, hi = sorted((float(low), float(high)))
    price = float(mid)
    if direction == Direction.BUY and lo > price:
        return "BUY_ZONE_ABOVE_CURRENT_PRICE", "BUY alert must be below current price or already interacting."
    if direction == Direction.SELL and hi < price:
        return "SELL_ZONE_BELOW_CURRENT_PRICE", "SELL alert must be above current price or already interacting."
    return "", ""


def install_prompt_market_side_policy() -> None:
    from . import institutional_two_zone as zoning
    current = zoning._candidate_zone
    if getattr(current, "_master_sniper_market_side", False):
        return

    def wrapped(candidate, snapshot, liq, context, index):
        zone, diag = current(candidate, snapshot, liq, context, index)
        if zone is None:
            return zone, diag
        code, reason = _market_side_rejection(zone.original_direction, zone.zone_low, zone.zone_high, snapshot.mid)
        if not code:
            return zone, diag
        out = dict(diag or {})
        out.update({"current_price": round(float(snapshot.mid), 5), "rejection_code": code, "rejection_reason": reason})
        return None, out

    wrapped._master_sniper_market_side = True
    zoning._candidate_zone = wrapped


def _reachability_bucket(zone: Zone, snapshot: MarketSnapshot) -> tuple[int, float]:
    h1a = max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9)
    distance_atr = _distance(float(snapshot.mid), float(zone.zone_low), float(zone.zone_high)) / h1a
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
    # B+ is executable at its reduced risk budget; do not demote it into a
    # watch-only ranking tier. Grade still ranks quality within executable zones.
    execution_tier = 0 if zone.grade in {Grade.A_PLUS, Grade.A, Grade.B_PLUS} else 1
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 9}.get(zone.grade, 9)
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(str(zone.source_tf), 9)
    reach_bucket, distance_atr = _reachability_bucket(zone, snapshot)
    return (execution_tier, int(zone.touch_count), reach_bucket, grade_rank, tf_rank, -float(zone.location_score), distance_atr, -int(zone.source_ts))


def install_zone_rank_policy() -> None:
    from . import institutional_two_zone as zoning
    zoning._rank = intraday_zone_rank


def _clean_zone(zone: Zone) -> None:
    zone.core_method = str(zone.core_method or "").replace("PROMPT_SWEEP_ROOM_GEOMETRY", "MASTER_SNIPER_COMPOSITE_GEOMETRY").replace("MASTER_SNIPER_SOURCE_EXACT", "MASTER_SNIPER_COMPOSITE_GEOMETRY")
    zone.invalidation_rule = "Closed M15 body acceptance beyond the Master Sniper structural envelope invalidates the zone. Wick-only liquidity raids do not invalidate."
    conf = set(zone.confluences)
    for legacy in ("CORE_100_150_POINTS", "ENVELOPE_200_300_POINTS", "PROFESSIONAL_SOURCE_TF_CORE_WIDTH", "PROFESSIONAL_SOURCE_TF_ENVELOPE_WIDTH", "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM", "SWEEP_ROOM_RESERVED", "SOURCE_CANDLE_EXACT_CORE", "SOURCE_CANDLE_EXACT_ENVELOPE"):
        conf.discard(legacy)
    conf.update({"SOURCE_CANDLE_ANCHORED", "STRUCTURAL_LIQUIDITY_IN_MASTER_SNIPER_AREA", "NO_SYNTHETIC_ZONE_EXPANSION"})
    zone.confluences = sorted(conf)
    zone.independent_confluence_count = len(zone.confluences)
    cleaned = []
    for raw in zone.notes:
        text = str(raw)
        if text.startswith(("core_width_points:", "envelope_width_points:", "sweep_room_points:", "core_width_pips:", "envelope_width_pips:", "sweep_room_pips:")):
            continue
        if text.startswith("Core is source-anchored") or text.startswith("Core/envelope use source-timeframe") or text.startswith("MASTER SNIPER: core and envelope are exact source-candle"):
            continue
        cleaned.append(text)
    cleaned.append("MASTER SNIPER: zone is source-anchored composite institutional structure; source + directional structural liquidity define the area without fixed-width/ATR manufacture.")
    zone.notes = cleaned


def apply_pip_display_contract(analysis: Analysis, snapshot: MarketSnapshot) -> Analysis:
    """Final public truth pass. Despite the legacy name, no width contract is applied."""
    if analysis is None:
        return analysis
    for zone in analysis.zones:
        _clean_zone(zone)

    policy = dict(analysis.execution_policy or {})
    zone_map = dict(policy.get("public_zone_map") or {})
    for side in ("sell", "buy"):
        entry = zone_map.get(side)
        if isinstance(entry, dict):
            entry = dict(entry)
            if entry.get("zone_id"):
                entry["audit_zone_id"] = str(entry["zone_id"])
            entry.pop("zone_id", None)
            for key in list(entry):
                if "width_" in key or key in {"sweep_room_points", "sweep_room_pips", "core_contract_pips", "envelope_contract_pips", "minimum_sweep_room_pips"}:
                    entry.pop(key, None)
            entry["geometry_authority"] = "MASTER_SNIPER_SOURCE_PLUS_STRUCTURAL_LIQUIDITY"
            entry["synthetic_expansion_allowed"] = False
            zone_map[side] = entry

    for key in list(zone_map):
        if key.startswith(("core_width_", "envelope_width_", "min_sweep_room_")) or key in {"geometry_by_source_tf", "width_display_unit", "xau_points_per_pip"}:
            zone_map.pop(key, None)
    zone_map.update({
        "prompt_contract_ref": PROMPT_ZONE_CONTRACT,
        "geometry_authority": "MASTER_SNIPER_TOTAL_AUTHORITY",
        "fixed_width_padding": False,
        "remote_liquidity_envelope_expansion": False,
        "structural_liquidity_may_extend_beyond_single_source_candle": True,
        "equal_high_low_are_liquidity_objects_only": True,
        "buy_zone_must_be_below_or_interacting": True,
        "sell_zone_must_be_above_or_interacting": True,
        "wrong_side_zone_is_rejected_not_flipped": True,
        "reachability_is_ranking_only": True,
        "bplus_execution_authority": True,
    })
    policy["public_zone_map"] = zone_map
    policy["zone_geometry"] = {
        "authority": "MASTER_SNIPER_TOTAL_AUTHORITY",
        "core": "NATIVE_H4_H1_SOURCE_CORE",
        "envelope": "SOURCE_PLUS_DIRECTIONAL_STRUCTURAL_LIQUIDITY",
        "fixed_width_padding": False,
        "atr_padding": False,
        "remote_liquidity_expansion": False,
    }
    primary = [x for x in list(policy.get("primary") or []) if x not in {"CORE_100_150_POINTS", "ENVELOPE_200_300_POINTS", "MINIMUM_50_POINT_DISTAL_SWEEP_ROOM", "PROFESSIONAL_SOURCE_TF_CORE_WIDTH", "PROFESSIONAL_SOURCE_TF_ENVELOPE_WIDTH", "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM", "SOURCE_EXACT_CORE_AND_ENVELOPE", "STRUCTURAL_LIQUIDITY_ALREADY_INSIDE_SOURCE"}]
    for rule in ("ACTUAL_H4_H1_INSTITUTIONAL_SOURCE_ANCHOR", "SOURCE_PLUS_STRUCTURAL_LIQUIDITY_AREA", "NO_SYNTHETIC_ZONE_EXPANSION", "BUY_BELOW_OR_INTERACTING_WITH_CURRENT_PRICE", "SELL_ABOVE_OR_INTERACTING_WITH_CURRENT_PRICE", "EQH_EQL_LIQUIDITY_ONLY", "BPLUS_EXECUTABLE_REDUCED_RISK"):
        if rule not in primary:
            primary.append(rule)
    policy["primary"] = primary
    analysis.execution_policy = policy

    brief = str(analysis.trader_brief or "")
    brief += " MASTER SNIPER TOTAL AUTHORITY: zones are anchored to real H4/H1 institutional sources and may include the structurally-related BSL/SSL outside a single source candle. Fixed-width/ATR manufacture remains disabled. Source-exact containment is not a rejection rule."
    analysis.trader_brief = brief
    return analysis
