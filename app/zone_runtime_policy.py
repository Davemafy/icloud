from __future__ import annotations

from .engine import atr
from .models import Analysis, Direction, Grade, MarketSnapshot, Zone

# MASTER SNIPER TOTAL AUTHORITY
# Zone geometry comes only from the actual H4/H1 institutional source candle.
# Liquidity, FVG, PSY, volume and DXY are evidence/confluence. They must never
# manufacture, stretch, or hard-reject an otherwise valid institutional source.
XAU_POINTS_PER_PIP = 10.0
MIN_SWEEP_ROOM_POINTS = 0.0
MIN_SWEEP_ROOM_PIPS = 0.0
PROMPT_ZONE_CONTRACT = "MASTER_SNIPER_TOTAL_AUTHORITY_V6578"

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
    return {"core_min": 0.0, "core_max": 0.0, "envelope_min": 0.0, "envelope_max": 0.0}


def install_zone_geometry_policy() -> None:
    """Install Master Sniper source-first zoning into the base engine.

    The prompt asks us to locate the institutional source that caused the move and
    then use liquidity/FVG/PSY/etc. as confirmation. Therefore a source is not
    rejected merely because a BSL/SSL object is outside that source candle.
    """
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
            # Prefer liquidity naturally inside the source, but do not make that a
            # hard qualification rule. The Master Sniper prompt treats liquidity as
            # institutional context/objective, not as permission to create a zone.
            inside = source_low <= price <= source_high
            directional = (
                price >= core_low
                if candidate.direction == Direction.SELL
                else price <= core_high
            )
            edge = abs(price - (core_high if candidate.direction == Direction.SELL else core_low))
            options.append((0 if inside else 1, 0 if directional else 1, tf_rank.get(tf, 9), edge, float(level.distance), level))
        if not options:
            return None
        options.sort(key=lambda row: row[:-1])
        return options[0][-1]

    def build_geometry(candidate, core_low, core_high, level, snapshot):
        source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
        # Geometry is the actual institutional source. Never expand it to capture a
        # remote liquidity object and never reject it because liquidity sits outside.
        if core_low < source_low - 1e-9 or core_high > source_high + 1e-9:
            return None
        liquidity_price = float(level.price)
        distal_room = (
            max(0.0, source_high - liquidity_price)
            if candidate.direction == Direction.SELL
            else max(0.0, liquidity_price - source_low)
        )
        return source_low, source_high, distal_room

    zoning._normalize_core = normalize_core
    zoning._select_liquidity = select_liquidity
    zoning._build_geometry = build_geometry

    # A valid source may interact even when its strongest structural liquidity is
    # contextual rather than physically inside the candle. Entry/management/exit
    # logic remains unchanged; this only removes the old zoning veto.
    def zone_health_allows_interaction(zone, snapshot):
        if zone.state.value != "ACTIVE" or zone.grade not in {Grade.A_PLUS, Grade.A, Grade.B_PLUS}:
            return False
        return zoning.evaluate_zone_state(zone, snapshot.xau_m15, snapshot.atr_m15).value == "ACTIVE"

    zoning._zone_health_allows_interaction = zone_health_allows_interaction


def _distance(price: float, low: float, high: float) -> float:
    lo, hi = sorted((float(low), float(high)))
    if lo <= price <= hi:
        return 0.0
    return lo - price if price < lo else price - hi


def _market_side_rejection(direction: Direction, low: float, high: float, mid: float) -> tuple[str, str]:
    # Master Sniper asks for the best BUY and SELL levels for the day. A valid
    # institutional zone is not deleted merely because price has already moved to
    # the other side. Market side affects ranking/current relevance, not existence.
    return "", ""


def install_prompt_market_side_policy() -> None:
    # Kept as a compatibility hook. There is intentionally no hard side rejection.
    return None


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
    execution_tier = 0 if zone.grade in {Grade.A_PLUS, Grade.A, Grade.B_PLUS} else 1
    grade_rank = {Grade.A_PLUS: 0, Grade.A: 1, Grade.B_PLUS: 2, Grade.REJECT: 9}.get(zone.grade, 9)
    tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(str(zone.source_tf), 9)
    reach_bucket, distance_atr = _reachability_bucket(zone, snapshot)
    return (execution_tier, int(zone.touch_count), reach_bucket, grade_rank, tf_rank, -float(zone.location_score), distance_atr, -int(zone.source_ts))


def install_zone_rank_policy() -> None:
    from . import institutional_two_zone as zoning
    zoning._rank = intraday_zone_rank


def _clean_zone(zone: Zone) -> None:
    zone.core_method = str(zone.core_method or "").replace("PROMPT_SWEEP_ROOM_GEOMETRY", "MASTER_SNIPER_SOURCE_FIRST")
    zone.invalidation_rule = "Closed M15 body acceptance beyond the actual institutional source envelope invalidates the zone. Wick-only liquidity raids do not invalidate."
    conf = set(zone.confluences)
    for legacy in (
        "CORE_100_150_POINTS", "ENVELOPE_200_300_POINTS",
        "PROFESSIONAL_SOURCE_TF_CORE_WIDTH", "PROFESSIONAL_SOURCE_TF_ENVELOPE_WIDTH",
        "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM", "SWEEP_ROOM_RESERVED",
    ):
        conf.discard(legacy)
    conf.update({"SOURCE_CANDLE_EXACT_CORE", "SOURCE_CANDLE_EXACT_ENVELOPE", "NO_SYNTHETIC_ZONE_EXPANSION"})

    # Correct the old label if the attached structural liquidity is contextual.
    attached_price = None
    for raw in zone.notes:
        text = str(raw)
        if text.startswith("attached_liquidity:") and "@" in text:
            try:
                attached_price = float(text.rsplit("@", 1)[1])
            except (TypeError, ValueError):
                attached_price = None
    if attached_price is not None and not (float(zone.zone_low) <= attached_price <= float(zone.zone_high)):
        conf.discard("LIQUIDITY_IN_MARKED_ZONE")
        conf.discard("BSL_IN_MARKED_ZONE")
        conf.discard("SSL_IN_MARKED_ZONE")
        conf.add("STRUCTURAL_LIQUIDITY_CONTEXT")

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
    cleaned.append("MASTER SNIPER: institutional source creates the zone; liquidity/FVG/PSY/volume/DXY confirm, rank or target it but do not manufacture or veto it.")
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
        "authority": "MASTER_SNIPER_PROMPT_TOTAL",
        "geometry_authority": "ACTUAL_H4_H1_SOURCE_CANDLE_ONLY",
        "fixed_width_padding": False,
        "remote_liquidity_envelope_expansion": False,
        "liquidity_is_confluence_not_zone_permission": True,
        "equal_high_low_are_liquidity_objects_only": True,
        "market_side_is_ranking_not_zone_existence": True,
        "reachability_is_ranking_only": True,
        "execution_trade_management_exit_frozen": True,
    })
    policy["public_zone_map"] = zone_map
    policy["zone_geometry"] = {
        "authority": "MASTER_SNIPER_SOURCE_FIRST",
        "core": "ACTUAL_SOURCE_BODY_OR_NATIVE_SOURCE_CORE",
        "envelope": "ACTUAL_SOURCE_CANDLE_HIGH_LOW",
        "fixed_width_padding": False,
        "atr_padding": False,
        "remote_liquidity_expansion": False,
        "liquidity_hard_veto": False,
    }
    primary = [x for x in list(policy.get("primary") or []) if x not in {
        "CORE_100_150_POINTS", "ENVELOPE_200_300_POINTS", "MINIMUM_50_POINT_DISTAL_SWEEP_ROOM",
        "PROFESSIONAL_SOURCE_TF_CORE_WIDTH", "PROFESSIONAL_SOURCE_TF_ENVELOPE_WIDTH",
        "MINIMUM_50_PIP_DISTAL_SWEEP_ROOM", "STRUCTURAL_LIQUIDITY_ALREADY_INSIDE_SOURCE",
        "BUY_BELOW_OR_INTERACTING_WITH_CURRENT_PRICE", "SELL_ABOVE_OR_INTERACTING_WITH_CURRENT_PRICE",
    }]
    for rule in (
        "MASTER_SNIPER_PROMPT_TOTAL_AUTHORITY", "ACTUAL_H4_H1_INSTITUTIONAL_SOURCE_CANDLE",
        "SOURCE_EXACT_CORE_AND_ENVELOPE", "NO_SYNTHETIC_ZONE_EXPANSION",
        "LIQUIDITY_FVG_PSY_VOLUME_DXY_ARE_CONFLUENCE_NOT_ZONE_PERMISSION",
        "EQH_EQL_LIQUIDITY_ONLY", "M15_HEALTH_M1_TIMING",
        "EXECUTION_MANAGEMENT_EXIT_FROZEN_DURING_ZONING_FIX",
    ):
        if rule not in primary:
            primary.append(rule)
    policy["primary"] = primary
    analysis.execution_policy = policy

    brief = str(analysis.trader_brief or "")
    brief += (
        " MASTER SNIPER TOTAL AUTHORITY: institutional H4/H1 source first. The actual source candle defines geometry. "
        "Liquidity, FVG, psychological levels, volume and DXY confirm/rank/target the source but cannot manufacture, stretch or hard-reject it. "
        "M15 validates health; M1 times entry. Execution, trade management and exit logic are frozen while zoning is corrected."
    )
    analysis.trader_brief = brief
    return analysis
