from __future__ import annotations

from .engine import atr
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone

# MASTER SNIPER TOTAL AUTHORITY
# Zone geometry comes only from the actual H4/H1 institutional source candle.
# No fixed-width core padding, envelope padding, ATR expansion, remote-liquidity
# expansion or minimum sweep-room manufacture is allowed.
XAU_POINTS_PER_PIP = 10.0
MIN_SWEEP_ROOM_POINTS = 0.0
MIN_SWEEP_ROOM_PIPS = 0.0
PROMPT_ZONE_CONTRACT = "MASTER_SNIPER_SOURCE_EXACT_V6577"

# Legacy compatibility names. They are deliberately zero because width contracts
# no longer qualify or manufacture a zone.
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
    # Compatibility seam used by the old dynamic continuation module. Returning
    # zero width makes that legacy synthetic re-zone fail closed rather than
    # manufacture a replacement outside the Master Sniper source candle.
    return {"core_min": 0.0, "core_max": 0.0, "envelope_min": 0.0, "envelope_max": 0.0}


def install_zone_geometry_policy() -> None:
    """Install source-exact Master Sniper zoning into the base engine."""
    from . import institutional_two_zone as zoning

    def normalize_core(candidate, snapshot):
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
            # Structural liquidity must ALREADY be inside the source candle.
            if not (source_low <= price <= source_high):
                continue
            # Preserve the prompt's directional relationship to the tactical core.
            if candidate.direction == Direction.SELL and price < core_low:
                continue
            if candidate.direction == Direction.BUY and price > core_high:
                continue
            edge = abs(price - (core_high if candidate.direction == Direction.SELL else core_low))
            options.append((tf_rank.get(tf, 9), edge, float(level.distance), level))
        if not options:
            return None
        options.sort(key=lambda row: row[:-1])
        return options[0][-1]

    def build_geometry(candidate, core_low, core_high, level, snapshot):
        source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
        liquidity_price = float(level.price)
        # Core and structural liquidity must both be naturally contained by the
        # source candle. Never stretch the envelope to make a candidate qualify.
        if core_low < source_low - 1e-9 or core_high > source_high + 1e-9:
            return None
        if liquidity_price < source_low - 1e-9 or liquidity_price > source_high + 1e-9:
            return None
        distal_room = (
            source_high - liquidity_price
            if candidate.direction == Direction.SELL
            else liquidity_price - source_low
        )
        if distal_room < -1e-9:
            return None
        return source_low, source_high, max(0.0, distal_room)

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
    execution_tier = 0 if zone.grade in {Grade.A_PLUS, Grade.A} else 1
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 9}.get(zone.grade, 9)
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(str(zone.source_tf), 9)
    reach_bucket, distance_atr = _reachability_bucket(zone, snapshot)
    return (execution_tier, int(zone.touch_count), reach_bucket, grade_rank, tf_rank, -float(zone.location_score), distance_atr, -int(zone.source_ts))


def install_zone_rank_policy() -> None:
    from . import institutional_two_zone as zoning
    zoning._rank = intraday_zone_rank


def _clean_zone(zone: Zone) -> None:
    zone.core_method = str(zone.core_method or "").replace("PROMPT_SWEEP_ROOM_GEOMETRY", "MASTER_SNIPER_SOURCE_EXACT")
    zone.invalidation_rule = "Closed M15 body acceptance beyond the actual institutional source envelope invalidates the zone. Wick-only liquidity raids do not invalidate."
    conf = set(zone.confluences)
    for legacy in ("CORE_100_150_POINTS", "ENVELOPE_200_300_POINTS", "PROFESSIONAL_SOURCE_TF_CORE_WIDTH", "PROFESSIONAL_SOURCE_TF_ENVELOPE_WIDTH", "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM", "SWEEP_ROOM_RESERVED"):
        conf.discard(legacy)
    conf.update({"SOURCE_CANDLE_EXACT_CORE", "SOURCE_CANDLE_EXACT_ENVELOPE", "NO_SYNTHETIC_ZONE_EXPANSION"})
    zone.confluences = sorted(conf)
    zone.independent_confluence_count = len(zone.confluences)
    cleaned = []
    for raw in zone.notes:
        text = str(raw)
        if text.startswith(("core_width_points:", "envelope_width_points:", "sweep_room_points:", "core_width_pips:", "envelope_width_pips:", "sweep_room_pips:")):
            continue
        if text.startswith("Core is source-anchored") or text.startswith("Core/envelope use source-timeframe"):
            continue
        cleaned.append(text)
    cleaned.append("MASTER SNIPER: core and envelope are exact source-candle geometry; no fixed-width padding or remote-liquidity expansion is permitted.")
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
            entry["geometry_authority"] = "ACTUAL_INSTITUTIONAL_SOURCE_CANDLE"
            entry["synthetic_expansion_allowed"] = False
            zone_map[side] = entry

    for key in list(zone_map):
        if key.startswith(("core_width_", "envelope_width_", "min_sweep_room_")) or key in {"geometry_by_source_tf", "width_display_unit", "xau_points_per_pip"}:
            zone_map.pop(key, None)
    zone_map.update({
        "prompt_contract_ref": PROMPT_ZONE_CONTRACT,
        "geometry_authority": "ACTUAL_H4_H1_SOURCE_CANDLE_ONLY",
        "fixed_width_padding": False,
        "remote_liquidity_envelope_expansion": False,
        "liquidity_must_already_exist_inside_source_envelope": True,
        "equal_high_low_are_liquidity_objects_only": True,
        "buy_zone_must_be_below_or_interacting": True,
        "sell_zone_must_be_above_or_interacting": True,
        "wrong_side_zone_is_rejected_not_flipped": True,
        "reachability_is_ranking_only": True,
    })
    policy["public_zone_map"] = zone_map
    policy["zone_geometry"] = {
        "authority": "MASTER_SNIPER_SOURCE_EXACT",
        "core": "ACTUAL_SOURCE_BODY_OR_NATIVE_SOURCE_CORE",
        "envelope": "ACTUAL_SOURCE_CANDLE_HIGH_LOW",
        "fixed_width_padding": False,
        "atr_padding": False,
        "remote_liquidity_expansion": False,
    }
    primary = [x for x in list(policy.get("primary") or []) if x not in {"CORE_100_150_POINTS", "ENVELOPE_200_300_POINTS", "MINIMUM_50_POINT_DISTAL_SWEEP_ROOM", "PROFESSIONAL_SOURCE_TF_CORE_WIDTH", "PROFESSIONAL_SOURCE_TF_ENVELOPE_WIDTH", "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM"}]
    for rule in ("ACTUAL_H4_H1_INSTITUTIONAL_SOURCE_CANDLE", "SOURCE_EXACT_CORE_AND_ENVELOPE", "NO_SYNTHETIC_ZONE_EXPANSION", "STRUCTURAL_LIQUIDITY_ALREADY_INSIDE_SOURCE", "BUY_BELOW_OR_INTERACTING_WITH_CURRENT_PRICE", "SELL_ABOVE_OR_INTERACTING_WITH_CURRENT_PRICE", "EQH_EQL_LIQUIDITY_ONLY"):
        if rule not in primary:
            primary.append(rule)
    policy["primary"] = primary
    analysis.execution_policy = policy

    brief = str(analysis.trader_brief or "")
    brief += " MASTER SNIPER SOURCE-EXACT authority: every published zone must come from the actual H4/H1 institutional source candle. Fixed-width core/envelope padding, ATR padding and remote-liquidity envelope expansion are disabled. Structural liquidity must already exist inside the source envelope."
    analysis.trader_brief = brief
    return analysis
