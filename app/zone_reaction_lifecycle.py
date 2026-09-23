from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .execution_ownership_migration import ensure_execution_ownership_schema
from .zone_publication_migration import ensure_zone_publication_schema
from .models import Analysis, Direction, MarketSnapshot, Zone, ZoneState
from .db import connect

REACTION_LIFECYCLE_CONTRACT = "INSTITUTIONAL_ZONE_REACTION_LIFECYCLE_V6561"
TERMINAL = {"OBJECTIVE_COMPLETE", "INVALIDATED", "INVALIDATED_AFTER_REACTION"}


def _reaction_key(zone: Zone) -> str:
    source_ts = int(zone.source_ts or 0)
    if source_ts:
        return f"{zone.original_direction.value}|{zone.source_tf}|{source_ts}"
    return (
        f"{zone.original_direction.value}|{zone.source_tf}|0|"
        f"{float(zone.core_low):.2f}|{float(zone.core_high):.2f}"
    )


def _note_int(zone: Zone, prefix: str, default: int = 0) -> int:
    for note in list(zone.notes or []):
        text = str(note)
        if not text.startswith(prefix):
            continue
        try:
            return int(float(text.split(":", 1)[1]))
        except (TypeError, ValueError, IndexError):
            return default
    return default


def _geometry_signature(zone: Zone) -> str:
    """Stable exact-publication identity for the user-facing execution geometry."""
    return "|".join(
        (
            str(zone.zone_id),
            zone.original_direction.value,
            str(zone.source_tf),
            str(int(zone.source_ts or 0)),
            f"{float(zone.core_low):.5f}",
            f"{float(zone.core_high):.5f}",
            f"{float(zone.zone_low):.5f}",
            f"{float(zone.zone_high):.5f}",
        )
    )


def _publication_key(zone: Zone) -> str:
    return f"{_reaction_key(zone)}|{_geometry_signature(zone)}"


def publication_state_for_zone(zone: Zone) -> dict[str, Any]:
    """Return publication/live-contact truth for this exact geometry only."""
    if not SETTINGS.paper_only:
        return {}
    ensure_zone_publication_schema()
    with connect() as db:
        row = db.execute(
            """
            SELECT publication_key,reaction_key,geometry_signature,first_analysis_id,
                   latest_analysis_id,zone_id,direction,source_tf,source_ts,
                   core_low,core_high,zone_low,zone_high,first_published_at,last_seen_at,
                   publication_qualified_mitigations,publication_raw_core_contacts,
                   live_core_touched_at,live_core_touch_basis,live_core_touch_price,
                   live_core_touch_analysis_id,status
            FROM zone_publications WHERE publication_key=?
            """,
            (_publication_key(zone),),
        ).fetchone()
    return dict(row) if row is not None else {}


def apply_publication_truth(analysis: Analysis) -> Analysis:
    """Expose exact publication-time versus live-contact truth on zones/dashboard."""
    if not SETTINGS.paper_only:
        return analysis
    ensure_zone_publication_schema()
    policy = dict(analysis.execution_policy or {})
    public = dict(policy.get("public_zone_map") or {})
    truth: dict[str, Any] = {}
    for zone in analysis.zones:
        state = publication_state_for_zone(zone)
        if not state:
            continue
        first_published = int(state.get("first_published_at") or 0)
        live_touch = int(state.get("live_core_touched_at") or 0)
        status = "LIVE_CONTACT_CONFIRMED" if live_touch else "RETEST_ONLY_NO_LIVE_CONTACT"
        additions = {
            "geometry_published_at": first_published,
            "publication_qualified_mitigations": int(state.get("publication_qualified_mitigations") or 0),
            "publication_raw_core_contacts": int(state.get("publication_raw_core_contacts") or 0),
            "live_core_touched_at": live_touch,
            "live_core_touch_basis": str(state.get("live_core_touch_basis") or ""),
            "live_core_touch_price": float(state.get("live_core_touch_price") or 0.0),
            "publication_execution_status": status,
        }
        truth[zone.zone_id] = additions
        zone.notes = [
            n for n in zone.notes
            if not str(n).startswith("geometry_published_at:")
            and not str(n).startswith("publication_qualified_mitigations:")
            and not str(n).startswith("publication_raw_core_contacts:")
            and not str(n).startswith("live_core_touched_at:")
            and not str(n).startswith("live_core_touch_basis:")
            and not str(n).startswith("live_core_touch_price:")
            and not str(n).startswith("publication_execution_status:")
        ] + [
            f"geometry_published_at:{first_published}",
            f"publication_qualified_mitigations:{additions['publication_qualified_mitigations']}",
            f"publication_raw_core_contacts:{additions['publication_raw_core_contacts']}",
            f"live_core_touched_at:{live_touch}",
            f"live_core_touch_basis:{additions['live_core_touch_basis'] or 'NONE'}",
            f"live_core_touch_price:{additions['live_core_touch_price']:.5f}",
            f"publication_execution_status:{status}",
        ]
        side = zone.original_direction.value.lower()
        side_map = dict(public.get(side) or {})
        side_map.update(additions)
        public[side] = side_map
    policy["public_zone_map"] = public
    policy["zone_publication_truth"] = {
        "contract": "EXACT_GEOMETRY_PUBLICATION_EXECUTION_TRUTH_V6561",
        "historical_contacts_never_create_execution_authority": True,
        "live_handoff_requires_post_publication_contact": True,
        "zones": truth,
    }
    analysis.execution_policy = policy
    return analysis


def register_analysis_zones(analysis: Analysis) -> None:
    """Persist source lifecycle plus an exact-geometry publication ledger.

    Source lifecycle can survive re-selection. Execution truth cannot: each exact
    user-facing geometry gets a new publication timestamp and baseline touch count.
    Contacts that happened before that timestamp remain research/freshness evidence
    only and can never manufacture a live M1 handoff.
    """
    if not SETTINGS.paper_only:
        return
    ensure_execution_ownership_schema()
    ensure_zone_publication_schema()
    with connect() as db:
        for zone in analysis.zones:
            if zone.state != ZoneState.ACTIVE:
                continue
            key = _reaction_key(zone)
            raw_contacts = _note_int(zone, "raw_core_touch_episodes:", int(zone.touch_count))
            publication_key = _publication_key(zone)
            signature = _geometry_signature(zone)

            db.execute(
                """
                INSERT OR IGNORE INTO zone_publications(
                    publication_key,reaction_key,geometry_signature,first_analysis_id,latest_analysis_id,
                    zone_id,direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,
                    first_published_at,last_seen_at,publication_qualified_mitigations,
                    publication_raw_core_contacts,status
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    publication_key,key,signature,analysis.analysis_id,analysis.analysis_id,
                    zone.zone_id,zone.original_direction.value,zone.source_tf,int(zone.source_ts or 0),
                    float(zone.core_low),float(zone.core_high),float(zone.zone_low),float(zone.zone_high),
                    int(analysis.generated_at),int(analysis.generated_at),int(zone.touch_count),
                    int(raw_contacts),"PUBLISHED",
                ),
            )
            db.execute(
                """
                UPDATE zone_publications SET
                    latest_analysis_id=?,last_seen_at=?,status=CASE
                        WHEN live_core_touched_at>0 THEN 'LIVE_CONTACT_CONFIRMED'
                        ELSE 'PUBLISHED'
                    END
                WHERE publication_key=?
                """,
                (analysis.analysis_id,int(analysis.generated_at),publication_key),
            )

            db.execute(
                """
                INSERT OR IGNORE INTO zone_reactions(
                    reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                    direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                    first_seen_at,last_seen_at,target1,target2,target3,runner,best_price,mfe_price,last_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    key,analysis.analysis_id,analysis.analysis_id,zone.zone_id,zone.zone_id,
                    zone.original_direction.value,zone.source_tf,int(zone.source_ts or 0),
                    float(zone.core_low),float(zone.core_high),float(zone.zone_low),float(zone.zone_high),
                    zone.grade.value,"ARMED",int(analysis.generated_at),int(analysis.generated_at),
                    float(zone.original_target1 or 0),float(zone.original_target2 or 0),
                    float(zone.original_target3 or 0),float(zone.original_runner or 0),
                    float(zone.core_low if zone.original_direction == Direction.SELL else zone.core_high),
                    0.0,"ZONE_PUBLISHED",
                ),
            )
            db.execute(
                """
                UPDATE zone_reactions SET
                    latest_analysis_id=?,
                    latest_zone_id=CASE WHEN ownership_acquired_at=0 THEN ? ELSE latest_zone_id END,
                    last_seen_at=?,
                    grade=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE grade END,
                    core_low=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE core_low END,
                    core_high=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE core_high END,
                    zone_low=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE zone_low END,
                    zone_high=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE zone_high END,
                    target1=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE target1 END,
                    target2=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE target2 END,
                    target3=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE target3 END,
                    runner=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE runner END
                WHERE reaction_key=?
                """,
                (
                    analysis.analysis_id,zone.zone_id,int(analysis.generated_at),zone.grade.value,
                    float(zone.core_low),float(zone.core_high),float(zone.zone_low),float(zone.zone_high),
                    float(zone.original_target1 or 0),float(zone.original_target2 or 0),
                    float(zone.original_target3 or 0),float(zone.original_runner or 0),key,
                ),
            )


def _body(bar) -> float:
    return abs(float(bar.close) - float(bar.open))


def _accepted_invalidation(row: Any, snapshot: MarketSnapshot) -> bool:
    bars = snapshot.xau_m15
    if len(bars) < 2:
        return False
    a = float(snapshot.atr_m15 or 0.0)
    if a <= 0:
        return False
    sell = str(row["direction"]) == Direction.SELL.value
    boundary = float(row["zone_high"] if sell else row["zone_low"])

    def frac(bar) -> float:
        body = max(_body(bar), 1e-9)
        top = max(float(bar.open), float(bar.close))
        bottom = min(float(bar.open), float(bar.close))
        beyond = max(0.0, top - max(bottom, boundary)) if sell else max(0.0, min(top, boundary) - bottom)
        return beyond / body

    last = bars[-1]
    beyond = float(last.close) > boundary if sell else float(last.close) < boundary
    single = (
        beyond
        and frac(last) >= SETTINGS.m15_single_accept_body_fraction
        and _body(last) >= SETTINGS.m15_single_accept_body_atr * a
    )
    x, y = bars[-2], bars[-1]
    two_closes = (
        (float(x.close) > boundary and float(y.close) > boundary)
        if sell else
        (float(x.close) < boundary and float(y.close) < boundary)
    )
    two = (
        two_closes
        and _body(x) >= SETTINGS.m15_double_accept_body_atr * a
        and _body(y) >= SETTINGS.m15_double_accept_body_atr * a
    )
    return bool(single or two)


def _publication_contact(row: Any, snapshot: MarketSnapshot) -> tuple[bool, str, float]:
    """Detect only contact that can be proven after this exact geometry was published."""
    published_at = int(row["first_published_at"] or 0)
    if published_at <= 0 or int(snapshot.sent_at) < published_at:
        return False, "", 0.0

    low = float(row["core_low"])
    high = float(row["core_high"])
    bid = float(snapshot.bid)
    ask = float(snapshot.ask)
    if ask >= low and bid <= high:
        return True, "LIVE_QUOTE_OVERLAP", float(snapshot.mid)

    # Fail-safe bar evidence: the M15 bar itself must have opened after publication.
    # A bar already in progress when the geometry was first published is ignored,
    # because its high/low can contain pre-publication price action.
    for bar in reversed(list(snapshot.xau_m15)[-3:]):
        if int(bar.ts) < published_at:
            continue
        if float(bar.high) >= low and float(bar.low) <= high:
            return True, "POST_PUBLICATION_M15_BAR", float(bar.close)
    return False, "", 0.0


def update_zone_publication_contacts(snapshot: MarketSnapshot, analysis: Analysis | None = None) -> None:
    """Latch live contact only for geometries that are in the active published map."""
    if not SETTINGS.paper_only:
        return
    ensure_zone_publication_schema()

    current = analysis
    if current is None:
        with connect() as db:
            latest = db.execute(
                "SELECT payload FROM analyses ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if latest is not None:
            try:
                current = Analysis.model_validate_json(latest["payload"])
            except Exception:
                current = None
    with connect() as db:
        if current is not None and current.zones:
            keys = [_publication_key(zone) for zone in current.zones if zone.state == ZoneState.ACTIVE]
            if not keys:
                return
            placeholders = ",".join("?" for _ in keys)
            rows = db.execute(
                f"""
                SELECT * FROM zone_publications
                WHERE publication_key IN ({placeholders})
                  AND COALESCE(live_core_touched_at,0)=0
                ORDER BY last_seen_at DESC
                """,
                tuple(keys),
            ).fetchall()
            current_analysis_id = current.analysis_id
        else:
            latest_pub = db.execute(
                "SELECT latest_analysis_id FROM zone_publications ORDER BY last_seen_at DESC LIMIT 1"
            ).fetchone()
            current_analysis_id = str(latest_pub["latest_analysis_id"] or "") if latest_pub is not None else ""
            if not current_analysis_id:
                return
            rows = db.execute(
                """
                SELECT * FROM zone_publications
                WHERE latest_analysis_id=? AND COALESCE(live_core_touched_at,0)=0
                ORDER BY last_seen_at DESC
                """,
                (current_analysis_id,),
            ).fetchall()
        for row in rows:
            touched, basis, price = _publication_contact(row, snapshot)
            if not touched:
                continue
            db.execute(
                """
                UPDATE zone_publications SET
                    live_core_touched_at=?,live_core_touch_basis=?,live_core_touch_price=?,
                    live_core_touch_analysis_id=?,status='LIVE_CONTACT_CONFIRMED',last_seen_at=?
                WHERE publication_key=? AND COALESCE(live_core_touched_at,0)=0
                """,
                (
                    int(snapshot.sent_at),basis,float(price),current_analysis_id,int(snapshot.sent_at),
                    row["publication_key"],
                ),
            )


def _favourable_extreme(row: Any, snapshot: MarketSnapshot) -> float:
    sell = str(row["direction"]) == Direction.SELL.value
    values = [float(snapshot.mid)]
    if snapshot.xau_m15:
        last = snapshot.xau_m15[-1]
        values.append(float(last.low if sell else last.high))
    old = float(row["best_price"] or 0.0)
    if old:
        values.append(old)
    return min(values) if sell else max(values)


def _mfe(row: Any, best: float) -> float:
    authority = str(row["ownership_authority"] or "") if "ownership_authority" in row.keys() else ""
    anchor = float(row["ownership_anchor_price"] or 0.0) if "ownership_anchor_price" in row.keys() else 0.0
    if authority not in {"LIQUIDITY_REVERSAL_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF"} or anchor <= 0:
        anchor = float(row["core_low"] if str(row["direction"]) == Direction.SELL.value else row["core_high"])
    if str(row["direction"]) == Direction.SELL.value:
        return max(0.0, anchor - best)
    return max(0.0, best - anchor)


def _crossed(direction: str, best: float, target: float) -> bool:
    if target <= 0:
        return False
    return best <= target if direction == Direction.SELL.value else best >= target


def _objective_anchor(row: Any) -> float:
    """Return the price from which objective progress is allowed to begin."""
    acquired_at = int(row["ownership_acquired_at"] or 0) if "ownership_acquired_at" in row.keys() else 0
    ownership_anchor = float(row["ownership_anchor_price"] or 0.0) if "ownership_anchor_price" in row.keys() else 0.0
    if acquired_at > 0 and ownership_anchor > 0:
        return ownership_anchor
    return float(row["core_low"] if str(row["direction"]) == Direction.SELL.value else row["core_high"])


def _target_live_from_anchor(direction: str, target: float, anchor: float) -> bool:
    """A target already behind the activation anchor was never completed by this thesis."""
    if target <= 0 or anchor <= 0:
        return False
    return target < anchor if direction == Direction.SELL.value else target > anchor


def update_zone_reactions(snapshot: MarketSnapshot) -> None:
    """Advance persisted zone lifecycle from live/closed market evidence.

    Historical interaction remains independent from execution ownership. A normal
    WATCH interaction may be recorded and even confirm a reaction without ever
    gaining the right to block another direction. Liquidity-reversal and proven
    outer-zone sweep handoffs can own execution without touching the tactical core,
    so their explicitly acquired/reaction-confirmed lifecycle is still advanced
    toward objectives from the actual ownership anchor.
    """
    if not SETTINGS.paper_only:
        return
    ensure_execution_ownership_schema()
    ensure_zone_publication_schema()
    # Idempotent safety: direct callers get the same publication-time guard as the
    # normal snapshot/service pipeline.
    update_zone_publication_contacts(snapshot)
    now = int(snapshot.sent_at)
    cutoff = now - 7 * 24 * 3600
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM zone_reactions WHERE first_seen_at>=? ORDER BY first_seen_at DESC",
            (cutoff,),
        ).fetchall()
        for row in rows:
            status = str(row["status"] or "ARMED")
            if status in TERMINAL:
                continue

            if _accepted_invalidation(row, snapshot):
                after_reaction = bool(row["reaction_confirmed_at"])
                db.execute(
                    "UPDATE zone_reactions SET status=?,invalidated_at=?,last_reason=?,last_seen_at=? WHERE reaction_key=?",
                    (
                        "INVALIDATED_AFTER_REACTION" if after_reaction else "INVALIDATED",
                        now,
                        "M15_ACCEPTED_INVALIDATION_AFTER_REACTION" if after_reaction else "M15_ACCEPTED_INVALIDATION",
                        now,row["reaction_key"],
                    ),
                )
                continue

            touched_at = int(row["core_touched_at"] or 0)
            reaction_confirmed_at = int(row["reaction_confirmed_at"] or 0)
            ownership_acquired_at = int(row["ownership_acquired_at"] or 0)

            # Source lifecycle is historical research. New execution truth is latched
            # in zone_publications and requires post-publication contact with the
            # exact current geometry. We deliberately do not infer a new touch here
            # from an old source-level M15 high/low.
            if not touched_at:
                pub = db.execute(
                    """
                    SELECT live_core_touched_at FROM zone_publications
                    WHERE reaction_key=? AND COALESCE(live_core_touched_at,0)>0
                    ORDER BY live_core_touched_at ASC LIMIT 1
                    """,
                    (row["reaction_key"],),
                ).fetchone()
                if pub is not None:
                    touched_at = int(pub["live_core_touched_at"] or 0)
                    if touched_at:
                        status = "INTERACTING" if not reaction_confirmed_at else status
                        db.execute(
                            "UPDATE zone_reactions SET status=?,core_touched_at=?,last_reason=?,last_seen_at=? WHERE reaction_key=?",
                            (status,touched_at,"POST_PUBLICATION_TACTICAL_CORE_INTERACTION",now,row["reaction_key"]),
                        )

            # Normal zone-reaction research starts after a proven post-publication
            # core touch. Explicit liquidity-reversal or zone-sweep handoffs are
            # already M15-confirmed and may advance from their ownership anchor.
            # liquidity-reversal or zone-sweep handoffs are already M15-confirmed
            # and may advance from their ownership anchor without touching the core.
            if not touched_at and not (ownership_acquired_at and reaction_confirmed_at):
                continue

            best = _favourable_extreme(row, snapshot)
            mfe = _mfe(row, best)
            m15_atr = max(float(snapshot.atr_m15 or 0.0), float(snapshot.point or 0.01))
            confirmation_distance = max(0.50 * m15_atr, float(snapshot.point or 0.01) * 100.0)
            if not reaction_confirmed_at and touched_at and mfe >= confirmation_distance:
                reaction_confirmed_at = now
                status = "REACTION_CONFIRMED"

            direction = str(row["direction"])
            target1 = float(row["target1"] or 0.0)
            target2 = float(row["target2"] or 0.0)
            target3 = float(row["target3"] or 0.0)
            t1_hit = int(row["target1_hit_at"] or 0)
            t2_hit = int(row["target2_hit_at"] or 0)
            t3_hit = int(row["target3_hit_at"] or 0)
            objective_anchor = _objective_anchor(row)
            t1_live = _target_live_from_anchor(direction, target1, objective_anchor)
            t2_live = _target_live_from_anchor(direction, target2, objective_anchor)
            t3_live = _target_live_from_anchor(direction, target3, objective_anchor)
            if not t1_hit and t1_live and _crossed(direction, best, target1):
                t1_hit = now
            if not t2_hit and t2_live and _crossed(direction, best, target2):
                t2_hit = now
            if not t3_hit and t3_live and _crossed(direction, best, target3):
                t3_hit = now

            valid_targets = [
                target for target, live in ((target1,t1_live),(target2,t2_live),(target3,t3_live))
                if target > 0 and live
            ]
            deepest_hit = False
            if valid_targets:
                deepest = valid_targets[-1]
                deepest_hit = _crossed(direction, best, deepest)

            if deepest_hit and reaction_confirmed_at:
                status = "OBJECTIVE_COMPLETE"
                reason = "DEEPEST_PLANNED_LIQUIDITY_OBJECTIVE_REACHED"
                completed_at = now
            elif (t1_hit or t2_hit or t3_hit) and reaction_confirmed_at:
                status = "OBJECTIVE_IN_PROGRESS"
                reason = "LIQUIDITY_OBJECTIVE_PROGRESS"
                completed_at = int(row["objective_complete_at"] or 0)
            elif reaction_confirmed_at:
                status = "REACTION_CONFIRMED"
                if str(row["ownership_authority"] or "") == "LIQUIDITY_REVERSAL_HANDOFF" and not touched_at:
                    reason = "LIQUIDITY_REVERSAL_HANDOFF_REACTION_CONFIRMED"
                else:
                    reason = "INSTITUTIONAL_REACTION_CONFIRMED"
                completed_at = int(row["objective_complete_at"] or 0)
            else:
                reason = "TACTICAL_CORE_INTERACTION"
                completed_at = int(row["objective_complete_at"] or 0)

            db.execute(
                """
                UPDATE zone_reactions SET
                    status=?,reaction_confirmed_at=?,target1_hit_at=?,target2_hit_at=?,target3_hit_at=?,
                    objective_complete_at=?,best_price=?,mfe_price=?,last_reason=?,last_seen_at=?
                WHERE reaction_key=?
                """,
                (
                    status,reaction_confirmed_at,t1_hit,t2_hit,t3_hit,completed_at,
                    best,mfe,reason,now,row["reaction_key"],
                ),
            )


def lifecycle_summary(limit: int = 20) -> list[dict[str, Any]]:
    ensure_execution_ownership_schema()
    ensure_zone_publication_schema()
    limit = max(1, min(int(limit), 100))
    with connect() as db:
        rows = db.execute(
            """
            SELECT reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                   direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                   first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
                   target1,target2,target3,target1_hit_at,target2_hit_at,target3_hit_at,
                   objective_complete_at,invalidated_at,best_price,mfe_price,last_reason,
                   ownership_acquired_at,ownership_authority,ownership_analysis_id,ownership_anchor_price
            FROM zone_reactions ORDER BY COALESCE(ownership_acquired_at,reaction_confirmed_at,core_touched_at,first_seen_at) DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def attach_lifecycle(analysis: Analysis) -> Analysis:
    policy = dict(analysis.execution_policy or {})
    records = lifecycle_summary(20)
    policy["zone_reaction_lifecycle"] = {
        "contract": REACTION_LIFECYCLE_CONTRACT,
        "persistence": "SURVIVES_PRIMARY_RESELECTION_AND_ZONE_MAP_REMOVAL",
        "historical_geometry_and_targets_freeze_after_core_interaction": True,
        "zone_validity_independent_of_target_map": True,
        "interaction_is_not_execution_ownership": True,
        "execution_ownership_requires_explicit_handoff": True,
        "exact_geometry_publication_truth": True,
        "historical_contacts_before_publication_are_research_only": True,
        "live_handoff_requires_post_publication_contact": True,
        "reaction_confirmation": "POST_PUBLICATION_CORE_INTERACTION_THEN_FAVOURABLE_MOVE_AT_LEAST_MAX_0_5_M15_ATR_OR_10_PIPS_OR_EXPLICIT_LIQUIDITY_REVERSAL_HANDOFF",
        "terminal_states": sorted(TERMINAL),
        "records": records,
    }
    analysis.execution_policy = policy
    return analysis
