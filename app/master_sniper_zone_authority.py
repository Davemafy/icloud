from __future__ import annotations

"""Master Sniper publication authority for the institutional zone engine.

DEMO/PAPER ONLY.

The underlying institutional_two_zone module remains responsible for discovering
source candles, liquidity, mitigation history, M15 invalidation and M1 execution
handoff.  This layer controls which discovered zone is allowed to become the
front-facing intraday alert map.

The key rule is location truth:
* BUY is publishable only below current price or while price is interacting.
* SELL is publishable only above current price or while price is interacting.

A structurally valid zone on the wrong side of price remains diagnostic/context;
it must never be relabelled as today's actionable BUY/SELL alert.  No opposite
side zone is forced merely to keep a two-zone display populated.
"""

from typing import Callable


def install_master_sniper_zone_authority() -> None:
    from . import institutional_two_zone as engine
    from .models import Direction, Grade, ZoneState

    if getattr(engine, "_MASTER_SNIPER_ZONE_AUTHORITY_INSTALLED", False):
        return

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

    def master_sniper_rank(zone, snapshot) -> tuple:
        """Rank today's alert before remote HTF context.

        Location truth and executable quality lead the ordering.  HTF source
        hierarchy still matters, but it cannot make a remote or wrong-side zone
        today's alert merely because its source timeframe is larger.
        """
        side_penalty = 0 if _alert_side_valid(zone, snapshot) else 1
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

    # apply_two_zone_institutional_map resolves _rank at runtime, therefore this
    # replaces candidate ordering without duplicating the discovery/grade engine.
    engine._rank = master_sniper_rank

    def apply_master_sniper_map(analysis, snapshot):
        zones = list(original_apply(analysis, snapshot))

        published = []
        suppressed = []
        for zone in zones:
            if zone.state == ZoneState.ACTIVE and _alert_side_valid(zone, snapshot):
                published.append(zone)
            else:
                suppressed.append(zone)

        analysis.zones = published
        if analysis.selected_zone_id and not any(
            z.zone_id == analysis.selected_zone_id for z in published
        ):
            analysis.selected_zone_id = ""

        # Never manufacture a selection.  If a valid A/A+ zone exists, prefer the
        # D1-context side; otherwise use the nearest valid executable alert.
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
                "engine": "MASTER_SNIPER_ZONE_AUTHORITY_2026_09_24",
                "master_sniper_prompt_authoritative": True,
                "alert_side_rule": {
                    "BUY": "BELOW_CURRENT_PRICE_OR_INTERACTING",
                    "SELL": "ABOVE_CURRENT_PRICE_OR_INTERACTING",
                },
                "wrong_side_structural_zone_is_context_only": True,
                "wrong_side_zone_can_receive_m1_authority": False,
                "no_second_zone_is_forced": True,
                "intraday_reachability_precedes_remote_htf_context": True,
                "published_zone_count": len(published),
                "suppressed_wrong_side_zone_ids": [z.zone_id for z in suppressed],
            }
        )
        policy["public_zone_map"] = zone_map
        analysis.execution_policy = policy

        # Rebuild the short brief so it cannot continue advertising a zone that
        # Master Sniper publication authority has suppressed.
        labels = []
        for zone in published:
            labels.append(
                f"{zone.original_direction.value}={zone.zone_low:.2f}-{zone.zone_high:.2f} "
                f"(core={zone.core_low:.2f}-{zone.core_high:.2f},{zone.source_tf},"
                f"grade={zone.grade.value})"
            )
        summary = "; ".join(labels) if labels else "none"
        analysis.trader_brief = (
            f"D1 context={analysis.overall_bias.value}. Master Sniper active execution map: "
            f"{summary}. BUY alerts must be below current price or already interacting; "
            f"SELL alerts must be above current price or already interacting. Wrong-side "
            f"HTF zones remain context only and receive no M1 execution authority. "
            f"H4/H1 source, liquidity, freshness and M15 invalidation remain mandatory; "
            f"M1 times entry only. No zone is forced to populate the map."
        )
        return analysis.zones

    engine.apply_two_zone_institutional_map = apply_master_sniper_map
    engine._MASTER_SNIPER_ZONE_AUTHORITY_INSTALLED = True
