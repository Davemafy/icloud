from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .db import audit, connect, latest_heartbeats
from .execution_ownership_migration import ensure_execution_ownership_schema
from .models import Analysis, Direction, MarketSnapshot, Zone, ZoneState
from .risk_matrix import execution_grade_eligible

THESIS_OWNERSHIP_CONTRACT = "INSTITUTIONAL_THESIS_OWNERSHIP_V6520"
ACTIVE_THESIS_STATUSES = {"INTERACTING", "REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}
CONTINUATION_STATUSES = {"REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}
EXECUTION_AUTHORITIES = {"HTF_CORE_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF", "LIQUIDITY_REVERSAL_HANDOFF"}
OWNER_REFRESH_BUFFER_M15_ATR = 0.30
OWNER_M1_HANDOFF_BUFFER_M15_ATR = 0.10
OWNER_MIN_BUFFER_POINTS = 5.0
SEQUENCE_HEARTBEAT_MAX_AGE_SECONDS = 45
LEGACY_OWNER_RELEASE_REASON = "CONTEXT_GRADE_V2_INELIGIBLE_OWNER_FLAT"

_AI_RULE = """
13. ACTIVE THESIS OWNERSHIP (PAPER/DEMO): zone interaction by itself never owns execution.
    A thesis may lock execution direction only after an explicit deterministic execution handoff has
    been acquired: HTF_CORE_HANDOFF, HTF_ZONE_SWEEP_HANDOFF, or LIQUIDITY_REVERSAL_HANDOFF. WATCH state alone or an exhausted
    repeatedly mitigated zone may remain visible, but cannot block the opposite side merely because price interacted with it.
    A+ and A are the only execution grades under the context-grade V2 risk contract; B+ is watch/research only and may not acquire new execution ownership. A legacy owner acquired under an older B+ contract is retired from execution locking only after a fresh Sequence heartbeat proves zero open positions; otherwise the system fails closed. Once an eligible qualified handoff has acquired ownership, that
    thesis remains sticky until M15 accepted invalidation or the deepest planned liquidity objective
    completes. A newly ranked opposite zone may remain visible as context but cannot steal M1 authority
    from the acquired thesis. Continuation still requires fresh M1 sweep -> MSS/BOS -> displacement ->
    dealing-range -> value/PD-array confirmation. If an acquired owner disappears from the current map,
    fail closed until lifecycle release or safe requalification.
"""


def install_thesis_ai_contract() -> None:
    """Extend the AI validator with the deterministic thesis-ownership rule."""
    from . import ai

    marker = "13. ACTIVE THESIS OWNERSHIP"
    if marker not in ai.SYSTEM:
        ai.SYSTEM += _AI_RULE


def _zone_reaction_key(zone: Zone) -> str:
    source_ts = int(zone.source_ts or 0)
    if source_ts:
        return f"{zone.original_direction.value}|{zone.source_tf}|{source_ts}"
    return (
        f"{zone.original_direction.value}|{zone.source_tf}|0|"
        f"{float(zone.core_low):.2f}|{float(zone.core_high):.2f}"
    )


def _sequence_position_truth(now: int) -> tuple[bool, int]:
    """Return (fresh, open_positions) from the live Sequence heartbeat.

    Grade-contract migration is allowed to retire a legacy non-executable owner
    only when the Sequence EA is freshly online and explicitly reports that no
    managed positions remain. Missing/stale telemetry therefore fails closed.
    """
    rows = latest_heartbeats(30)
    hb = next(
        (x for x in rows if str(x.get("ea") or "") == "InstitutionalSMC_SequenceEA"),
        None,
    )
    if hb is None:
        return False, 0
    hb_ts = int(hb.get("ts") or 0)
    if hb_ts <= 0 or int(now) - hb_ts > SEQUENCE_HEARTBEAT_MAX_AGE_SECONDS:
        return False, 0
    payload = hb.get("payload") if isinstance(hb.get("payload"), dict) else {}
    details = dict(payload.get("details") or {}) if isinstance(payload, dict) else {}
    try:
        open_positions = max(0, int(details.get("open_positions") or 0))
    except (TypeError, ValueError):
        return False, 0
    return True, open_positions


def _owner_execution_lock_eligible(owner: dict[str, Any]) -> bool:
    """Whether the frozen owner still qualifies to monopolize execution authority."""
    payload = str(owner.get("ownership_zone_payload") or "")
    if payload:
        try:
            zone = Zone.model_validate_json(payload)
            return execution_grade_eligible(zone)
        except Exception:
            # Fall through to the persisted grade. Ambiguous A/A+ rows are kept
            # fail-closed; known B+ legacy rows are the compatibility case.
            pass
    return str(owner.get("grade") or "").upper() != "B+"


def _retire_legacy_owner_execution_lock(owner: dict[str, Any], now: int) -> None:
    """Retire only the execution lock; keep the lifecycle row for audit/history."""
    key = str(owner.get("reaction_key") or "")
    if not key:
        return
    acquired_at = int(owner.get("ownership_acquired_at") or 0)
    authority = str(owner.get("ownership_authority") or "")
    reason = (
        f"EXECUTION_AUTHORITY_RELEASED:{LEGACY_OWNER_RELEASE_REASON}:"
        f"acquired_at={acquired_at}:authority={authority}"
    )
    with connect() as db:
        db.execute(
            """
            UPDATE zone_reactions
            SET ownership_acquired_at=0,last_reason=?,last_seen_at=?
            WHERE reaction_key=? AND ownership_acquired_at>0
              AND invalidated_at=0 AND objective_complete_at=0
            """,
            (reason, int(now), key),
        )
    audit(
        int(now),
        "thesis.execution_owner.released",
        f"reaction_key={key} reason={LEGACY_OWNER_RELEASE_REASON} "
        f"grade={owner.get('grade','')} authority={authority} acquired_at={acquired_at}",
    )


def _active_owner_row(now: int) -> dict[str, Any] | None:
    """Return the oldest still-live thesis that actually acquired execution authority."""
    ensure_execution_ownership_schema()
    cutoff = int(now) - 7 * 24 * 3600
    with connect() as db:
        table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='zone_reactions'"
        ).fetchone()
        if table is None:
            return None
        rows = db.execute(
            """
            SELECT reaction_key,latest_zone_id,direction,source_tf,source_ts,status,
                   core_low,core_high,zone_low,zone_high,grade,core_touched_at,
                   reaction_confirmed_at,target1,target2,target3,target1_hit_at,
                   target2_hit_at,target3_hit_at,objective_complete_at,invalidated_at,
                   best_price,mfe_price,last_reason,first_seen_at,last_seen_at,
                   ownership_acquired_at,ownership_authority,ownership_analysis_id,
                   ownership_anchor_price,ownership_zone_id,ownership_zone_payload
            FROM zone_reactions
            WHERE first_seen_at>=?
              AND ownership_acquired_at>0
              AND invalidated_at=0
              AND objective_complete_at=0
              AND status IN ('INTERACTING','REACTION_CONFIRMED','OBJECTIVE_IN_PROGRESS')
            ORDER BY ownership_acquired_at ASC, first_seen_at ASC
            """,
            (cutoff,),
        ).fetchall()
    if not rows:
        return None

    sequence_fresh, open_positions = _sequence_position_truth(int(now))
    for raw in rows:
        owner = dict(raw)
        if _owner_execution_lock_eligible(owner):
            return owner

        # v6.5.51 made B+ watch-only. Historical B+ locks created under the
        # older reduced-risk contract must not starve a fresh A/A+ opposite
        # setup forever once the old campaign is flat. We retire the execution
        # monopoly only with fresh, explicit Sequence position truth.
        if not sequence_fresh or open_positions > 0:
            owner["compat_execution_lock_protected"] = True
            owner["compat_execution_lock_reason"] = (
                "SEQUENCE_POSITIONS_OPEN"
                if open_positions > 0
                else "SEQUENCE_POSITION_TRUTH_UNAVAILABLE"
            )
            return owner

        _retire_legacy_owner_execution_lock(owner, int(now))

    return None


def active_owner_snapshot(now: int) -> dict[str, Any] | None:
    """Public read-only owner snapshot for scheduler refresh decisions."""
    if not SETTINGS.paper_only:
        return None
    return _active_owner_row(int(now))


def _owner_core_interaction(
    snapshot: MarketSnapshot,
    atr_fraction: float,
    allowed_statuses: set[str] | None = None,
) -> dict[str, Any] | None:
    owner = active_owner_snapshot(int(snapshot.sent_at))
    if owner is None:
        return None
    if allowed_statuses is not None and str(owner.get("status") or "") not in allowed_statuses:
        return None
    low, high = sorted((float(owner.get("core_low") or 0.0), float(owner.get("core_high") or 0.0)))
    if high <= low:
        return None
    px = float(snapshot.mid)
    if low <= px <= high:
        distance = 0.0
    else:
        distance = low - px if px < low else px - high
    point = max(float(snapshot.point or 0.01), 1e-9)
    m15a = max(float(snapshot.atr_m15 or 0.0), point)
    buffer_price = max(point * OWNER_MIN_BUFFER_POINTS, float(atr_fraction) * m15a)
    return owner if distance <= buffer_price else None


def owner_core_interacting(snapshot: MarketSnapshot) -> dict[str, Any] | None:
    """Broad refresh trigger when an acquired live thesis returns near its tactical core."""
    return _owner_core_interaction(snapshot, OWNER_REFRESH_BUFFER_M15_ATR)


def owner_m1_handoff_interacting(snapshot: MarketSnapshot) -> dict[str, Any] | None:
    """Strict refresh trigger for a confirmed acquired thesis entering M1 handoff range."""
    return _owner_core_interaction(
        snapshot,
        OWNER_M1_HANDOFF_BUFFER_M15_ATR,
        CONTINUATION_STATUSES,
    )


def _matches_owner(zone: Zone, owner: dict[str, Any]) -> bool:
    """Match only the frozen owner identity/geometry, never a newly re-ranked zone."""
    if zone.state != ZoneState.ACTIVE:
        return False
    if zone.original_direction.value != str(owner.get("direction", "")):
        return False

    ownership_zone_id = str(owner.get("ownership_zone_id") or "")
    if ownership_zone_id:
        return zone.zone_id == ownership_zone_id

    # Legacy rows created before the frozen-zone contract may not yet have an
    # ownership_zone_id. Accept the old id only when geometry still matches the
    # persisted lifecycle row; source timestamp alone is no longer sufficient.
    latest_zone_id = str(owner.get("latest_zone_id") or "")
    if latest_zone_id and zone.zone_id == latest_zone_id:
        return True
    source_ts = int(owner.get("source_ts") or 0)
    source_tf = str(owner.get("source_tf") or "")
    tol = 1e-6
    return bool(
        source_ts
        and int(zone.source_ts or 0) == source_ts
        and str(zone.source_tf) == source_tf
        and abs(float(zone.core_low) - float(owner.get("core_low") or 0.0)) <= tol
        and abs(float(zone.core_high) - float(owner.get("core_high") or 0.0)) <= tol
        and abs(float(zone.zone_low) - float(owner.get("zone_low") or 0.0)) <= tol
        and abs(float(zone.zone_high) - float(owner.get("zone_high") or 0.0)) <= tol
    )


def _ownership_zone_snapshot(owner: dict[str, Any]) -> Zone | None:
    """Restore the exact zone that acquired authority.

    ownership_analysis_id points to the analysis that granted the handoff, so old
    rows can be backfilled safely even if latest_zone_id was later re-ranked.
    """
    payload = str(owner.get("ownership_zone_payload") or "")
    if payload:
        try:
            zone = Zone.model_validate_json(payload)
            if zone.state == ZoneState.ACTIVE:
                return zone
        except Exception:
            pass

    analysis_id = str(owner.get("ownership_analysis_id") or "")
    if not analysis_id:
        return None
    try:
        with connect() as db:
            row = db.execute(
                "SELECT payload FROM analyses WHERE analysis_id=? ORDER BY ts DESC LIMIT 1",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        owning_analysis = Analysis.model_validate_json(str(row["payload"]))
        wanted = str(owner.get("ownership_zone_id") or "")
        zone = next(
            (
                z for z in owning_analysis.zones
                if (wanted and z.zone_id == wanted)
                or (not wanted and z.zone_id == owning_analysis.selected_zone_id)
            ),
            None,
        )
        if zone is None:
            return None
        with connect() as db:
            db.execute(
                """
                UPDATE zone_reactions
                SET ownership_zone_id=CASE WHEN ownership_zone_id='' THEN ? ELSE ownership_zone_id END,
                    ownership_zone_payload=CASE WHEN ownership_zone_payload='' THEN ? ELSE ownership_zone_payload END
                WHERE reaction_key=?
                """,
                (zone.zone_id, zone.model_dump_json(), str(owner.get("reaction_key") or "")),
            )
        owner["ownership_zone_id"] = zone.zone_id
        owner["ownership_zone_payload"] = zone.model_dump_json()
        return zone.model_copy(deep=True)
    except Exception:
        return None


def _owner_meta(owner: dict[str, Any], owner_zone: Zone | None) -> dict[str, Any]:
    status = str(owner.get("status") or "INTERACTING")
    direction = str(owner.get("direction") or Direction.NEUTRAL.value)
    return {
        "contract": THESIS_OWNERSHIP_CONTRACT,
        "locked": True,
        "direction": direction,
        "status": status,
        "reaction_key": str(owner.get("reaction_key") or ""),
        "source_tf": str(owner.get("source_tf") or ""),
        "source_ts": int(owner.get("source_ts") or 0),
        "owner_zone_id": str(owner.get("ownership_zone_id") or (owner_zone.zone_id if owner_zone is not None else "")),
        "owner_zone_present": owner_zone is not None,
        "ownership_acquired_at": int(owner.get("ownership_acquired_at") or 0),
        "ownership_authority": str(owner.get("ownership_authority") or ""),
        "ownership_analysis_id": str(owner.get("ownership_analysis_id") or ""),
        "ownership_anchor_price": float(owner.get("ownership_anchor_price") or 0.0),
        "reaction_confirmed_at": int(owner.get("reaction_confirmed_at") or 0),
        "target1_hit_at": int(owner.get("target1_hit_at") or 0),
        "target2_hit_at": int(owner.get("target2_hit_at") or 0),
        "target3_hit_at": int(owner.get("target3_hit_at") or 0),
        "same_direction_execution_only": True,
        "opposite_execution_blocked": True,
        "d1_context_cannot_override_live_thesis": True,
        "current_grade_downgrade_does_not_flip_thesis": True,
        "continuation_authority": status in CONTINUATION_STATUSES,
        "release_conditions": [
            "M15_ACCEPTED_INVALIDATION",
            "DEEPEST_PLANNED_LIQUIDITY_OBJECTIVE_REACHED",
        ],
        "fresh_m1_confirmation_required": True,
        "no_chase": True,
        "objective_open": True,
        "target1": float(owner.get("target1") or 0.0),
        "target2": float(owner.get("target2") or 0.0),
        "target3": float(owner.get("target3") or 0.0),
        "best_price": float(owner.get("best_price") or 0.0),
        "mfe_price": float(owner.get("mfe_price") or 0.0),
    }


def _handoff_reaction_instance(
    db,
    analysis: Analysis,
    snapshot: MarketSnapshot,
    zone: Zone,
    authority: str,
    anchor: float,
) -> tuple[str, Any] | tuple[str, None]:
    """Return a live lifecycle row, creating a fresh handoff instance when safe.

    A remote liquidity-reversal or proven outer-zone sweep can legitimately earn
    execution before the tactical core. If the base source row is historical/
    terminal (or absent because that source was requalified after its old lifecycle
    ended), do not let the stale row poison the new deterministic handoff. Preserve
    the old row and create a new analysis-scoped execution instance instead.

    HTF_CORE_HANDOFF remains strict: it must attach to an existing live lifecycle row.
    """
    base_key = _zone_reaction_key(zone)
    row = db.execute("SELECT * FROM zone_reactions WHERE reaction_key=?", (base_key,)).fetchone()
    terminal = bool(
        row is not None
        and (
            int(row["invalidated_at"] or 0)
            or int(row["objective_complete_at"] or 0)
            or str(row["status"] or "") not in ACTIVE_THESIS_STATUSES | {"ARMED"}
        )
    )
    if row is not None and not terminal:
        return base_key, row

    if authority not in {"LIQUIDITY_REVERSAL_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF"}:
        return base_key, None

    instance_key = f"{base_key}|OWN|{analysis.analysis_id}"
    existing = db.execute(
        "SELECT * FROM zone_reactions WHERE reaction_key=?",
        (instance_key,),
    ).fetchone()
    if existing is not None:
        return instance_key, existing

    now = int(snapshot.sent_at)
    preconfirmed_authority = authority in {"LIQUIDITY_REVERSAL_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF"}
    status = "REACTION_CONFIRMED" if preconfirmed_authority else "INTERACTING"
    reaction_confirmed_at = now if preconfirmed_authority else 0
    db.execute(
        """
        INSERT INTO zone_reactions(
            reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
            direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
            first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
            target1,target2,target3,runner,target1_hit_at,target2_hit_at,target3_hit_at,
            objective_complete_at,invalidated_at,best_price,mfe_price,last_reason,
            ownership_acquired_at,ownership_authority,ownership_analysis_id,ownership_anchor_price,
            ownership_zone_id,ownership_zone_payload
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            instance_key, analysis.analysis_id, analysis.analysis_id, zone.zone_id, zone.zone_id,
            zone.original_direction.value, zone.source_tf, int(zone.source_ts or 0),
            float(zone.core_low), float(zone.core_high), float(zone.zone_low), float(zone.zone_high),
            zone.grade.value, status, now, now, 0, reaction_confirmed_at,
            float(zone.original_target1 or 0.0), float(zone.original_target2 or 0.0),
            float(zone.original_target3 or 0.0), float(zone.original_runner or 0.0),
            0, 0, 0, 0, 0, float(anchor), 0.0,
            f"HANDOFF_INSTANCE_CREATED:{authority}",
            0, "", "", 0.0, "", "",
        ),
    )
    created = db.execute(
        "SELECT * FROM zone_reactions WHERE reaction_key=?",
        (instance_key,),
    ).fetchone()
    return instance_key, created


def acquire_execution_ownership(
    analysis: Analysis,
    snapshot: MarketSnapshot,
    authority: str,
    zone_id: str,
    anchor_price: float = 0.0,
) -> dict[str, Any] | None:
    """Persist thesis ownership only after a final approved execution handoff.

    HTF_CORE_HANDOFF originates from tactical-core M1_READY. HTF_ZONE_SWEEP_HANDOFF
    originates from a qualified envelope entry plus a proven structural-liquidity raid
    and M15 reclaim, so its lifecycle is already REACTION_CONFIRMED without a core touch.
    LIQUIDITY_REVERSAL_HANDOFF is likewise M15-confirmed before the remote context core.
    This function never creates a zone or an order.
    """
    if not SETTINGS.paper_only or authority not in EXECUTION_AUTHORITIES:
        return None
    zone = next((z for z in analysis.zones if z.zone_id == zone_id and z.state == ZoneState.ACTIVE), None)
    if zone is None or not execution_grade_eligible(zone):
        return None

    ensure_execution_ownership_schema()
    now = int(snapshot.sent_at)
    anchor = float(anchor_price or snapshot.mid)
    liquidity_authority = authority == "LIQUIDITY_REVERSAL_HANDOFF"
    zone_sweep_authority = authority == "HTF_ZONE_SWEEP_HANDOFF"
    with connect() as db:
        key, row = _handoff_reaction_instance(db, analysis, snapshot, zone, authority, anchor)
        if row is None:
            return None
        if int(row["invalidated_at"] or 0) or int(row["objective_complete_at"] or 0):
            return None
        status = str(row["status"] or "ARMED")
        if status not in ACTIVE_THESIS_STATUSES and not (
            (liquidity_authority or zone_sweep_authority) and status == "ARMED"
        ):
            return None

        db.execute(
            """
            UPDATE zone_reactions SET
                ownership_acquired_at=CASE WHEN ownership_acquired_at=0 THEN ? ELSE ownership_acquired_at END,
                ownership_authority=CASE WHEN ownership_acquired_at=0 OR ownership_authority='' THEN ? ELSE ownership_authority END,
                ownership_analysis_id=CASE WHEN ownership_acquired_at=0 OR ownership_analysis_id='' THEN ? ELSE ownership_analysis_id END,
                ownership_anchor_price=CASE WHEN ownership_acquired_at=0 OR ownership_anchor_price<=0 THEN ? ELSE ownership_anchor_price END,
                ownership_zone_id=CASE WHEN ownership_acquired_at=0 OR ownership_zone_id='' THEN ? ELSE ownership_zone_id END,
                ownership_zone_payload=CASE WHEN ownership_acquired_at=0 OR ownership_zone_payload='' THEN ? ELSE ownership_zone_payload END,
                reaction_confirmed_at=CASE WHEN ?=1 AND reaction_confirmed_at=0 THEN ? ELSE reaction_confirmed_at END,
                status=CASE
                    WHEN ?=1 AND status IN ('ARMED','INTERACTING') THEN 'REACTION_CONFIRMED'
                    ELSE status
                END,
                last_reason=?,last_seen_at=?
            WHERE reaction_key=?
            """,
            (
                now, authority, analysis.analysis_id, anchor, zone.zone_id, zone.model_dump_json(),
                1 if (liquidity_authority or zone_sweep_authority) else 0, now,
                1 if (liquidity_authority or zone_sweep_authority) else 0,
                f"EXECUTION_AUTHORITY_ACQUIRED:{authority}", now, key,
            ),
        )
        refreshed = db.execute("SELECT * FROM zone_reactions WHERE reaction_key=?", (key,)).fetchone()
    if refreshed is None:
        return None
    owner = dict(refreshed)
    policy = dict(analysis.execution_policy or {})
    policy["active_thesis"] = _owner_meta(owner, zone)
    analysis.execution_policy = policy
    zone.notes = [
        f"thesis_owner:{zone.original_direction.value}:{owner.get('status','INTERACTING')}",
        *[n for n in zone.notes if not str(n).startswith("thesis_owner:")],
    ]
    # Do not bake a point-in-time "ownership acquired" statement into the long
    # institutional brief. The persisted row is audit truth, while active_thesis is
    # the authoritative CURRENT lock state and may legitimately release later.
    return owner


def apply_thesis_ownership(analysis: Analysis, snapshot: MarketSnapshot) -> Zone | None:
    """Give a previously acquired live thesis precedence over newly ranked opposite zones."""
    if not SETTINGS.paper_only:
        return None

    owner = _active_owner_row(int(snapshot.sent_at))
    policy = dict(analysis.execution_policy or {})

    if owner is None:
        policy["active_thesis"] = {
            "contract": THESIS_OWNERSHIP_CONTRACT,
            "locked": False,
            "reason": "NO_ACQUIRED_NONTERMINAL_THESIS",
            "interaction_alone_never_locks": True,
        }
        analysis.execution_policy = policy
        return None

    previous_selected = analysis.selected_zone_id
    status = str(owner.get("status") or "INTERACTING")
    direction = str(owner.get("direction") or Direction.NEUTRAL.value)

    frozen = _ownership_zone_snapshot(owner)
    owner_zone = frozen if frozen is not None else next((z for z in analysis.zones if _matches_owner(z, owner)), None)

    if owner_zone is not None and frozen is not None:
        # Replace the newly ranked same-direction display zone with the exact zone
        # that acquired execution. This keeps the public map at one zone per side
        # while preventing geometry/id drift from stealing or blocking authority.
        replaced = False
        rebuilt: list[Zone] = []
        for current in analysis.zones:
            if current.original_direction.value == direction and not replaced:
                rebuilt.append(owner_zone)
                replaced = True
            elif current.original_direction.value != direction:
                rebuilt.append(current)
        if not replaced:
            rebuilt.insert(0, owner_zone)
        analysis.zones = rebuilt[:2]

    policy["active_thesis"] = _owner_meta(owner, owner_zone)
    analysis.execution_policy = policy

    if owner_zone is None:
        analysis.selected_zone_id = ""
        analysis.approved = False
        if "ACTIVE_THESIS_OWNER_SNAPSHOT_UNAVAILABLE" not in analysis.guards:
            analysis.guards.append("ACTIVE_THESIS_OWNER_SNAPSHOT_UNAVAILABLE")
        if "ACTIVE_THESIS_OWNER_NOT_IN_CURRENT_MAP" not in analysis.guards:
            analysis.guards.append("ACTIVE_THESIS_OWNER_NOT_IN_CURRENT_MAP")
        analysis.trader_brief += (
            f" Active acquired thesis lock={direction} ({status}, {owner.get('ownership_authority','')}). "
            "Its frozen ownership-zone snapshot is unavailable, so execution fails closed until lifecycle release."
        )
        return None

    analysis.selected_zone_id = owner_zone.zone_id
    owner_zone.notes = [
        f"thesis_owner:{direction}:{status}",
        *[n for n in owner_zone.notes if not str(n).startswith("thesis_owner:")],
    ]

    if previous_selected and previous_selected != owner_zone.zone_id:
        analysis.trader_brief += (
            f" Active acquired thesis lock={direction} ({status}) on {owner_zone.zone_id}; "
            f"newly ranked {previous_selected} remains map/context only and has no M1 authority until "
            "the acquired thesis is invalidated or completes its deepest liquidity objective."
        )
    else:
        analysis.trader_brief += (
            f" Active acquired thesis lock={direction} ({status}) on {owner_zone.zone_id}; same-direction M1 "
            "confirmation remains mandatory and opposite-side execution is blocked."
        )
    return owner_zone
