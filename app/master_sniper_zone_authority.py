from __future__ import annotations

"""Master Sniper authority for XAU institutional zone formation.

DEMO/PAPER ONLY.

This module is intentionally installed before analysis construction.  The Master
Sniper prompt is the zoning authority, not a publication filter placed on top of
legacy geometry.  The underlying engine still supplies audited structure,
liquidity, mitigation, M15 invalidation and M1 handoff, but it is not allowed to
manufacture a tactical core or stretch a source candle into a synthetic zone.

Formation truth:
* D1 = external context; H4 = primary institutional location; H1 = refinement/fallback.
* A zone must originate from an actual H4/H1 displacement/BOS source or an actual
  liquidity-sweep/rejection source followed by displacement.
* The tactical core is the REAL source-candle body/refinement.  It is never padded
  to a fixed width simply to satisfy a geometry constant.
* The outer envelope is the REAL source-candle range (H4 parent for H4>H1).  It is
  never expanded merely to pull a remote BSL/SSL into the zone.
* SELL requires genuine structural BSL already inside that source envelope, with
  distal sweep room naturally present inside the same source range.
* BUY requires genuine structural SSL already inside that source envelope, with
  distal sweep room naturally present inside the same source range.
* FVG, wick rejection, volume, premium/discount, PSY and DXY are confluence/context;
  none is allowed to manufacture location.
* BUY alerts are below current price or interacting; SELL alerts are above current
  price or interacting.  No opposite-side or reserve zone is forced.
* M15 judges health/accepted invalidation.  M1 times entry only.
"""

from typing import Callable


def install_master_sniper_zone_authority() -> None:
    from . import institutional_two_zone as engine
    from .models import Direction, Grade, ZoneState

    if getattr(engine, "_MASTER_SNIPER_ZONE_AUTHORITY_INSTALLED", False):
        return

    # ------------------------------------------------------------------
    # MASTER-SNIPER FORMATION OVERRIDES
    # ------------------------------------------------------------------
    # The old engine normalized every core to a fixed point width and could expand
    # the source range to make a liquidity level fit.  That is precisely the drift
    # this authority forbids.  apply_two_zone_institutional_map resolves these
    # helpers at runtime, so installing them here changes candidate formation BEFORE
    # mitigation, grading, selection and publication are calculated.

    def master_sniper_source_core(candidate, snapshot):
        lo, hi = sorted((float(candidate.core_low), float(candidate.core_high)))
        if hi <= lo:
            return lo, hi
        return lo, hi

    def master_sniper_select_liquidity(candidate, core_low, core_high, liq, snapshot):
        required = "BSL" if candidate.direction == Direction.SELL else "SSL"
        source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
        sweep_room = engine.MIN_SWEEP_ROOM_POINTS * engine._point(snapshot)
        tf_rank = {"D1": 0, "H4": 1, "H1": 2}
        options = []

        for level in liq:
            if required not in str(level.label).upper():
                continue
            tf = str(level.source_tf).upper()
            if tf not in {"D1", "H4", "H1"}:
                continue
            price = float(level.price)

            # Liquidity must already belong to the actual source candle.  Never
            # widen the zone to capture a nearby pivot after the fact.
            if not (source_low <= price <= source_high):
                continue

            if candidate.direction == Direction.SELL:
                if price < core_low:
                    continue
                room = source_high - price
                edge_distance = abs(price - core_high)
            else:
                if price > core_high:
                    continue
                room = price - source_low
                edge_distance = abs(core_low - price)

            if room + 1e-9 < sweep_room:
                continue
            options.append((tf_rank.get(tf, 9), edge_distance, float(level.distance), level))

        if not options:
            return None
        options.sort(key=lambda row: row[:-1])
        return options[0][-1]

    def master_sniper_source_geometry(candidate, core_low, core_high, level, snapshot):
        source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
        liquidity_price = float(level.price)
        sweep_room = engine.MIN_SWEEP_ROOM_POINTS * engine._point(snapshot)

        if not (source_low <= core_low <= core_high <= source_high):
            return None
        if not (source_low <= liquidity_price <= source_high):
            return None

        if candidate.direction == Direction.SELL:
            actual_room = source_high - liquidity_price
        else:
            actual_room = liquidity_price - source_low
        if actual_room + 1e-9 < sweep_room:
            return None

        # Exact source range.  No arbitrary minimum width, no remote-liquidity
        # expansion, no geometry manufactured from current price.
        return source_low, source_high, actual_room

    engine._normalize_core = master_sniper_source_core
    engine._select_liquidity = master_sniper_select_liquidity
    engine._build_geometry = master_sniper_source_geometry

    original_apply: Callable = engine.apply_two_zone_institutional_map

    def _interacting(zone, snapshot) -> bool:
        bid = float(snapshot.bid)
        ask = float(snapshot.ask)
        lo, hi = sorted((float(zone.zone_low), float(zone.zone_high)))
        return ask >= lo and bid <= hi

    def _alert_side_valid(zone, snapshot) -> bool:
        if _interacting(zone, snapshot):
            return True
        mid = float(snapshot.mid)
        if zone.original_direction == Direction.BUY:
            return float(zone.zone_high) < mid
        if zone.original_direction == Direction.SELL:
            return float(zone.zone_low) > mid
        return False

    def _master_source_evidence(zone) -> bool:
        conf = set(zone.confluences or [])
        source_ok = "SOURCE_CANDLE_ANCHORED" in conf
        liquidity_ok = "LIQUIDITY_IN_MARKED_ZONE" in conf
        impulse_ok = bool(
            {"INSTITUTIONAL_DISPLACEMENT", "LIQUIDITY_SWEEP_REJECTION"} & conf
        )
        return source_ok and liquidity_ok and impulse_ok

    def master_sniper_rank(zone, snapshot) -> tuple:
        side_penalty = 0 if _alert_side_valid(zone, snapshot) else 1
        evidence_penalty = 0 if _master_source_evidence(zone) else 1
        interacting_penalty = 0 if _interacting(zone, snapshot) else 1
        grade_rank = {
            Grade.A_PLUS: 0,
            Grade.A: 1,
            Grade.B_PLUS: 2,
            Grade.REJECT: 9,
        }.get(zone.grade, 9)
        distance = engine._distance(
            float(snapshot.mid), float(zone.zone_low), float(zone.zone_high)
        )
        tf_rank = {"H4>H1": 0, "H4": 1, "H1": 2}.get(zone.source_tf, 9)
        return (
            side_penalty,
            evidence_penalty,
            interacting_penalty,
            grade_rank,
            distance,
            tf_rank,
            int(zone.touch_count),
            0 if "HISTORICAL_DISPLACEMENT_FVG" in zone.confluences else 1,
            0 if "LIQUIDITY_SWEEP_REJECTION" in zone.confluences else 1,
            0 if "INSTITUTIONAL_DISPLACEMENT" in zone.confluences else 1,
            -float(zone.location_score),
            -int(zone.source_ts),
        )

    engine._rank = master_sniper_rank

    def apply_master_sniper_map(analysis, snapshot):
        zones = list(original_apply(analysis, snapshot))

        published = []
        suppressed = []
        for zone in zones:
            valid = (
                zone.state == ZoneState.ACTIVE
                and _alert_side_valid(zone, snapshot)
                and _master_source_evidence(zone)
            )
            if valid:
                published.append(zone)
            else:
                suppressed.append(zone)

        analysis.zones = published
        if analysis.selected_zone_id and not any(
            z.zone_id == analysis.selected_zone_id for z in published
        ):
            analysis.selected_zone_id = ""

        executable = [
            z for z in published
            if z.state == ZoneState.ACTIVE and engine.execution_grade_eligible(z)
        ]
        if not analysis.selected_zone_id and executable:
            context = analysis.overall_bias
            preferred = next(
                (z for z in executable if z.original_direction == context), None
            )
            if preferred is None:
                preferred = min(
                    executable,
                    key=lambda z: engine._distance(
                        float(snapshot.mid), float(z.zone_low), float(z.zone_high)
                    ),
                )
            analysis.selected_zone_id = preferred.zone_id

        policy = dict(analysis.execution_policy or {})
        zone_map = dict(policy.get("public_zone_map") or {})
        zone_map.update(
            {
                "engine": "MASTER_SNIPER_TOTAL_AUTHORITY_2026_09_24_V2",
                "master_sniper_prompt_authoritative": True,
                "master_sniper_controls_formation_not_only_publication": True,
                "core_geometry": "EXACT_SOURCE_CANDLE_BODY_OR_H1_REFINEMENT",
                "envelope_geometry": "EXACT_SOURCE_CANDLE_RANGE_OR_H4_PARENT",
                "fixed_width_core_normalization_disabled": True,
                "remote_liquidity_envelope_expansion_disabled": True,
                "liquidity_must_preexist_inside_source_envelope": True,
                "alert_side_rule": {
                    "BUY": "BELOW_CURRENT_PRICE_OR_INTERACTING",
                    "SELL": "ABOVE_CURRENT_PRICE_OR_INTERACTING",
                },
                "wrong_side_structural_zone_is_context_only": True,
                "wrong_side_zone_can_receive_m1_authority": False,
                "no_second_zone_is_forced": True,
                "intraday_reachability_precedes_remote_htf_context": True,
                "m15_health_only": True,
                "m1_timing_only": True,
                "published_zone_count": len(published),
                "suppressed_zone_ids": [z.zone_id for z in suppressed],
            }
        )
        policy["public_zone_map"] = zone_map
        analysis.execution_policy = policy

        labels = []
        for zone in published:
            labels.append(
                f"{zone.original_direction.value}={zone.zone_low:.2f}-{zone.zone_high:.2f} "
                f"(core={zone.core_low:.2f}-{zone.core_high:.2f},{zone.source_tf},"
                f"grade={zone.grade.value})"
            )
        summary = "; ".join(labels) if labels else "none"
        analysis.trader_brief = (
            f"D1 context={analysis.overall_bias.value}. MASTER SNIPER TOTAL AUTHORITY map: "
            f"{summary}. Zones originate from actual H4/H1 institutional source candles; "
            f"fixed-width core padding and remote-liquidity envelope expansion are disabled. "
            f"Required structural liquidity and distal sweep room must already exist inside "
            f"the source envelope. BUY alerts must be below price/interacting; SELL alerts "
            f"must be above price/interacting. FVG, PSY, volume and DXY are confluence only. "
            f"M15 validates health; M1 times entry. No zone is forced."
        )
        return analysis.zones

    engine.apply_two_zone_institutional_map = apply_master_sniper_map
    engine._MASTER_SNIPER_ZONE_AUTHORITY_INSTALLED = True
