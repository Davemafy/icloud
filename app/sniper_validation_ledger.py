from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from typing import Any

from .db import connect
from .models import Analysis, Zone
from .risk_matrix import original_risk_pct, zone_risk_context
from .zone_publication_migration import ensure_zone_publication_schema
from .execution_ownership_migration import ensure_execution_ownership_schema


VALIDATION_LEDGER_VERSION = "MASTER_SNIPER_VALIDATION_LEDGER_V2_CANONICAL_SOURCE_CORE"
_TRADE_EVENTS = {"ENTRY_OPENED", "POSITION_MARK", "POSITION_EXIT", "TP_HIT", "SL_HIT", "TRADE_CLOSED"}


def _json_obj(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if value in (None, ""):
        return {}
    try:
        out = json.loads(str(value))
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def _note_text(zone: Zone | None, prefix: str, default: str = "") -> str:
    if zone is None:
        return default
    for raw in list(zone.notes or []):
        text = str(raw)
        if text.startswith(prefix):
            return text.split(":", 1)[1] if ":" in text else default
    return default


def _note_int(zone: Zone | None, prefix: str, default: int = 0) -> int:
    try:
        return int(float(_note_text(zone, prefix, str(default))))
    except (TypeError, ValueError):
        return default


def _analysis_map(ids: set[str]) -> dict[str, Analysis]:
    ids = {str(x) for x in ids if str(x)}
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    with connect() as db:
        rows = db.execute(
            f"SELECT analysis_id,payload FROM analyses WHERE analysis_id IN ({marks})",
            tuple(sorted(ids)),
        ).fetchall()
    out: dict[str, Analysis] = {}
    for row in rows:
        try:
            out[str(row["analysis_id"])] = Analysis.model_validate_json(row["payload"])
        except Exception:
            continue
    return out


def _find_zone(analysis: Analysis | None, zone_id: str) -> Zone | None:
    if analysis is None:
        return None
    for zone in analysis.zones:
        if zone.zone_id == zone_id:
            return zone
    return None


def _append_event(events: list[dict], ts: int, event: str, **details: Any) -> None:
    ts = int(ts or 0)
    if ts <= 0:
        return
    row = {"ts": ts, "event": event}
    row.update({k: v for k, v in details.items() if v not in (None, "")})
    key = (
        row["ts"],
        row["event"],
        str(row.get("position_id") or ""),
        str(row.get("deal_id") or ""),
        str(row.get("reason") or ""),
    )
    if any(
        (
            int(x.get("ts") or 0),
            str(x.get("event") or ""),
            str(x.get("position_id") or ""),
            str(x.get("deal_id") or ""),
            str(x.get("reason") or ""),
        )
        == key
        for x in events
    ):
        return
    events.append(row)


def _audit_events(zone: Zone | None, published_at: int, window_end: int) -> list[dict]:
    if zone is None:
        return []
    audit = dict(zone.mitigation_audit or {})
    events: list[dict] = []

    def inside(ts: int) -> bool:
        return ts >= published_at and (window_end <= 0 or ts < window_end)

    for raw in list(audit.get("raw_contacts") or []):
        armed_at = int(raw.get("armed_at") or 0)
        touched_at = int(raw.get("core_touched_at") or 0)
        if inside(armed_at):
            _append_event(
                events,
                armed_at,
                "APPROACH_ARMED",
                approach_side=str(raw.get("campaign_approach_side") or raw.get("approach_side") or ""),
            )
        if inside(touched_at):
            _append_event(
                events,
                touched_at,
                "RAW_CORE_CONTACT",
                approach_side=str(raw.get("campaign_approach_side") or raw.get("approach_side") or ""),
                immediate_approach_side=str(raw.get("immediate_approach_side") or ""),
                role=str(raw.get("contact_role") or "RAW_CONTACT_ONLY"),
            )

    for raw in list(audit.get("events") or []):
        qualified = bool(raw.get("qualified"))
        ts = int(raw.get("qualified_at") or raw.get("bar_ts") or raw.get("core_touched_at") or 0)
        if not inside(ts):
            continue
        if qualified:
            _append_event(
                events,
                ts,
                "QUALIFIED_MITIGATION",
                qualified_index=int(raw.get("qualified_index") or 0),
                approach_side=str(raw.get("approach_side") or ""),
                exit_side=str(raw.get("exit_side") or ""),
                reason=str(raw.get("reason") or ""),
                grade_before=str(raw.get("grade_before") or ""),
                grade_after=str(raw.get("grade_after") or ""),
            )
        elif str(raw.get("event_type") or "").upper() == "INVALIDATION":
            _append_event(events, ts, "MITIGATION_AUDIT_INVALIDATION", reason=str(raw.get("reason") or ""))

    return events


def _feedback_rows(min_ts: int) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT id,ts,event,analysis_id,zone_id,price,details
            FROM feedback
            WHERE ts>=? AND UPPER(event)!='ML_CANDIDATE'
            ORDER BY ts ASC,id ASC
            LIMIT 10000
            """,
            (int(min_ts),),
        ).fetchall()
    return [dict(row) for row in rows]


def _validation_sample_key(row: dict) -> str:
    """Canonical research identity: institutional source + tactical core.

    Exact envelope publication records remain preserved in zone_publications for
    forensic audit. The validation ledger, however, must not count repeated
    reanalysis of the same source/core as independent samples.
    """
    return "|".join(
        (
            str(row.get("direction") or ""),
            str(row.get("source_tf") or ""),
            str(int(row.get("source_ts") or 0)),
            f"{float(row.get('core_low') or 0.0):.5f}",
            f"{float(row.get('core_high') or 0.0):.5f}",
        )
    )


def _canonicalize_publications(rows: list[dict], limit: int) -> list[dict]:
    grouped: dict[str, dict] = {}
    for raw in rows:
        row = dict(raw)
        key = _validation_sample_key(row)
        current = grouped.get(key)
        if current is None:
            row["validation_sample_key"] = key
            row["publication_observation_count"] = 1
            grouped[key] = row
            continue

        current["publication_observation_count"] = int(current.get("publication_observation_count") or 1) + 1

        row_published = int(row.get("first_published_at") or 0)
        cur_published = int(current.get("first_published_at") or 0)
        if row_published and (cur_published <= 0 or row_published < cur_published):
            current["first_published_at"] = row_published
            current["first_analysis_id"] = row.get("first_analysis_id")
            current["publication_qualified_mitigations"] = row.get("publication_qualified_mitigations")
            current["publication_raw_core_contacts"] = row.get("publication_raw_core_contacts")

        row_seen = int(row.get("last_seen_at") or 0)
        cur_seen = int(current.get("last_seen_at") or 0)
        if row_seen > cur_seen:
            current["last_seen_at"] = row_seen
            current["latest_analysis_id"] = row.get("latest_analysis_id")
            # Keep the latest visible envelope/zone label for audit display while
            # preserving the first publication clock above.
            for field in ("publication_key","geometry_signature","zone_id","zone_low","zone_high","status"):
                current[field] = row.get(field)

        row_touch = int(row.get("live_core_touched_at") or 0)
        cur_touch = int(current.get("live_core_touched_at") or 0)
        if row_touch and (cur_touch <= 0 or row_touch < cur_touch):
            current["live_core_touched_at"] = row_touch
            current["live_core_touch_basis"] = row.get("live_core_touch_basis")
            current["live_core_touch_price"] = row.get("live_core_touch_price")
            current["live_core_touch_analysis_id"] = row.get("live_core_touch_analysis_id")
            current["status"] = "LIVE_CONTACT_CONFIRMED"

    ordered = sorted(
        grouped.values(),
        key=lambda row: int(row.get("first_published_at") or 0),
        reverse=True,
    )
    return ordered[:limit]



def _zone_validation_sample_key(zone: Zone) -> str:
    return "|".join(
        (
            zone.original_direction.value,
            str(zone.source_tf or ""),
            str(int(zone.source_ts or 0)),
            f"{float(zone.core_low or 0.0):.5f}",
            f"{float(zone.core_high or 0.0):.5f}",
        )
    )


def _owner_lifecycle_by_sample() -> dict[str, dict]:
    """Return the authoritative acquired lifecycle row per canonical source/core.

    Execution handoffs can create analysis-scoped reaction instances whose key is
    suffixed with |OWN|..., while zone_publications keeps the base reaction key.
    Joining only on exact reaction_key therefore made a live owner appear ARMED
    in the research ledger. Prefer a nonterminal acquired instance for the same
    canonical source/core; otherwise retain the most recent acquired instance.
    """
    ensure_execution_ownership_schema()
    with connect() as db:
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
            WHERE ownership_acquired_at>0
            ORDER BY
                CASE
                    WHEN invalidated_at=0 AND objective_complete_at=0
                     AND status IN ('INTERACTING','REACTION_CONFIRMED','OBJECTIVE_IN_PROGRESS')
                    THEN 0 ELSE 1
                END,
                ownership_acquired_at DESC,
                last_seen_at DESC
            """
        ).fetchall()
    out: dict[str, dict] = {}
    for raw in rows:
        row = dict(raw)
        key = _validation_sample_key(row)
        if key not in out:
            out[key] = row
    return out


def _overlay_owner_lifecycle(publications: list[dict]) -> list[dict]:
    """Reconcile canonical publication rows with persisted owner-instance truth.

    This is observation-only. It never changes zone_publications or zone_reactions.
    The frozen owner payload can also restore an earlier exact publication/contact
    timestamp when later reanalysis created a new publication row for the same
    source/core.
    """
    owners = _owner_lifecycle_by_sample()
    if not owners:
        return publications

    lifecycle_fields = (
        "core_touched_at",
        "reaction_confirmed_at",
        "target1",
        "target2",
        "target3",
        "target1_hit_at",
        "target2_hit_at",
        "target3_hit_at",
        "objective_complete_at",
        "invalidated_at",
        "best_price",
        "mfe_price",
        "last_reason",
        "ownership_acquired_at",
        "ownership_authority",
        "ownership_analysis_id",
        "ownership_anchor_price",
        "ownership_zone_id",
    )

    for row in publications:
        key = _validation_sample_key(row)
        owner = owners.get(key)
        if owner is None:
            continue

        row["reaction_key"] = str(owner.get("reaction_key") or row.get("reaction_key") or "")
        row["lifecycle_status"] = str(owner.get("status") or row.get("lifecycle_status") or "")
        row["lifecycle_grade"] = str(owner.get("grade") or row.get("lifecycle_grade") or "")
        for field in lifecycle_fields:
            row[field] = owner.get(field)

        payload = str(owner.get("ownership_zone_payload") or "")
        if not payload:
            continue
        try:
            frozen = Zone.model_validate_json(payload)
        except Exception:
            continue
        if _zone_validation_sample_key(frozen) != key:
            continue

        frozen_published = _note_int(frozen, "geometry_published_at:", 0)
        current_published = int(row.get("first_published_at") or 0)
        if frozen_published > 0 and (current_published <= 0 or frozen_published < current_published):
            row["first_published_at"] = frozen_published
            row["publication_qualified_mitigations"] = _note_int(
                frozen,
                "publication_qualified_mitigations:",
                int(row.get("publication_qualified_mitigations") or 0),
            )
            row["publication_raw_core_contacts"] = _note_int(
                frozen,
                "publication_raw_core_contacts:",
                int(row.get("publication_raw_core_contacts") or 0),
            )

        frozen_touch = _note_int(frozen, "live_core_touched_at:", 0)
        current_touch = int(row.get("live_core_touched_at") or 0)
        if frozen_touch > 0 and (current_touch <= 0 or frozen_touch < current_touch):
            row["live_core_touched_at"] = frozen_touch
            row["live_core_touch_basis"] = _note_text(
                frozen, "live_core_touch_basis:", str(row.get("live_core_touch_basis") or "")
            )
            try:
                row["live_core_touch_price"] = float(
                    _note_text(
                        frozen,
                        "live_core_touch_price:",
                        str(row.get("live_core_touch_price") or 0.0),
                    )
                    or 0.0
                )
            except (TypeError, ValueError):
                pass
            row["status"] = "LIVE_CONTACT_CONFIRMED"

    return sorted(
        publications,
        key=lambda row: int(row.get("first_published_at") or 0),
        reverse=True,
    )


def _publication_rows(limit: int) -> list[dict]:
    ensure_execution_ownership_schema()
    ensure_zone_publication_schema()
    limit = max(1, min(int(limit), 250))
    # Select the most recently observed CANONICAL source/core samples first, then
    # pull every exact-geometry publication belonging to those samples. A bounded
    # raw-row LIMIT is unsafe here: frequent envelope refinements can create more
    # than hundreds of exact publications for one source/core and push the true
    # first publication/contact/execution outside the read window. That made a
    # previously executed sample appear new again after enough reanalysis.
    with connect() as db:
        rows = db.execute(
            """
            WITH canonical_keys AS (
                SELECT
                    direction,source_tf,source_ts,core_low,core_high,
                    MAX(last_seen_at) AS canonical_last_seen
                FROM zone_publications
                GROUP BY direction,source_tf,source_ts,core_low,core_high
                ORDER BY canonical_last_seen DESC
                LIMIT ?
            )
            SELECT
                p.*,
                r.status AS lifecycle_status,
                r.grade AS lifecycle_grade,
                r.core_touched_at,
                r.reaction_confirmed_at,
                r.target1,r.target2,r.target3,
                r.target1_hit_at,r.target2_hit_at,r.target3_hit_at,
                r.objective_complete_at,r.invalidated_at,
                r.best_price,r.mfe_price,r.last_reason,
                r.ownership_acquired_at,r.ownership_authority,
                r.ownership_analysis_id,r.ownership_anchor_price,
                r.ownership_zone_id
            FROM zone_publications p
            JOIN canonical_keys k
              ON k.direction=p.direction
             AND k.source_tf=p.source_tf
             AND k.source_ts=p.source_ts
             AND k.core_low=p.core_low
             AND k.core_high=p.core_high
            LEFT JOIN zone_reactions r ON r.reaction_key=p.reaction_key
            ORDER BY p.first_published_at DESC
            """,
            (limit,),
        ).fetchall()
    canonical = _canonicalize_publications([dict(row) for row in rows], limit)
    return _overlay_owner_lifecycle(canonical)


def build_validation_ledger(limit: int = 50) -> dict:
    """Read-only validation ledger built only from already-persisted truth.

    It does not create zones, modify grades, acquire ownership, change risk, alter
    /mt5/plan, or send orders. It is a research/audit view over publication,
    mitigation, lifecycle and MT5 journal evidence.
    """
    publications = _publication_rows(limit)
    if not publications:
        return {
            "contract": VALIDATION_LEDGER_VERSION,
            "paper_only": True,
            "read_only": True,
            "summary": {
                "publications": 0,
                "raw_publication_records": 0,
                "live_contacts": 0,
                "reaction_confirmed": 0,
                "reaction_confirmed_after_live_contact": 0,
                "reaction_confirmed_without_live_core_contact": 0,
                "invalidated_before_reaction": 0,
                "invalidated_after_reaction": 0,
                "objective_complete": 0,
                "executed_publications": 0,
                "reaction_rate_after_contact_pct": None,
                "execution_rate_after_contact_pct": None,
            },
            "rows": [],
        }

    ids: set[str] = set()
    for row in publications:
        ids.add(str(row.get("first_analysis_id") or ""))
        ids.add(str(row.get("latest_analysis_id") or ""))
    analyses = _analysis_map(ids)

    min_ts = min(int(row.get("first_published_at") or 0) for row in publications if int(row.get("first_published_at") or 0) > 0)
    feedback = _feedback_rows(min_ts)

    next_publication_by_zone: dict[str, int] = {}
    output: list[dict] = []
    for row in publications:
        zone_id = str(row.get("zone_id") or "")
        published_at = int(row.get("first_published_at") or 0)
        window_end = int(next_publication_by_zone.get(zone_id, 0))
        next_publication_by_zone[zone_id] = published_at

        first_analysis = analyses.get(str(row.get("first_analysis_id") or ""))
        latest_analysis = analyses.get(str(row.get("latest_analysis_id") or ""))
        first_zone = _find_zone(first_analysis, zone_id)
        latest_zone = _find_zone(latest_analysis, zone_id) or first_zone

        structural_grade = _note_text(first_zone, "structural_grade:", first_zone.grade.value if first_zone else str(row.get("lifecycle_grade") or ""))
        current_grade = _note_text(latest_zone, "current_execution_grade:", latest_zone.grade.value if latest_zone else structural_grade)
        qualified = _note_int(latest_zone, "qualified_mitigations:", int(row.get("publication_qualified_mitigations") or 0))
        raw_contacts = _note_int(latest_zone, "raw_core_touch_episodes:", int(row.get("publication_raw_core_contacts") or 0))
        risk_context = zone_risk_context(latest_zone) if latest_zone is not None else ("COUNTERTREND" if bool(getattr(first_zone, "countertrend", False)) else "TREND")
        base_risk = float(original_risk_pct(latest_zone)) if latest_zone is not None else 0.0

        events: list[dict] = []
        _append_event(events, published_at, "ZONE_PUBLISHED", analysis_id=str(row.get("first_analysis_id") or ""))

        live_touch = int(row.get("live_core_touched_at") or 0)
        if live_touch and (window_end <= 0 or live_touch < window_end):
            _append_event(
                events,
                live_touch,
                "LIVE_CORE_CONTACT",
                basis=str(row.get("live_core_touch_basis") or ""),
                price=float(row.get("live_core_touch_price") or 0.0),
            )

        events.extend(_audit_events(latest_zone, published_at, window_end))

        reaction_ts = int(row.get("reaction_confirmed_at") or 0)
        if reaction_ts and (window_end <= 0 or reaction_ts < window_end):
            _append_event(events, reaction_ts, "REACTION_CONFIRMED", reason=str(row.get("last_reason") or ""))

        handoff_ts = int(row.get("ownership_acquired_at") or 0)
        if handoff_ts and (window_end <= 0 or handoff_ts < window_end):
            _append_event(
                events,
                handoff_ts,
                "M1_HANDOFF_ACQUIRED",
                authority=str(row.get("ownership_authority") or ""),
                anchor_price=float(row.get("ownership_anchor_price") or 0.0),
            )

        for idx in (1, 2, 3):
            hit_ts = int(row.get(f"target{idx}_hit_at") or 0)
            if hit_ts and (window_end <= 0 or hit_ts < window_end):
                _append_event(events, hit_ts, f"TARGET_{idx}_HIT", price=float(row.get(f"target{idx}") or 0.0))

        invalidated_at = int(row.get("invalidated_at") or 0)
        if invalidated_at and (window_end <= 0 or invalidated_at < window_end):
            _append_event(
                events,
                invalidated_at,
                "ACCEPTED_INVALIDATION",
                reason=str(row.get("last_reason") or ""),
                after_reaction=bool(reaction_ts and reaction_ts <= invalidated_at),
            )

        complete_at = int(row.get("objective_complete_at") or 0)
        if complete_at and (window_end <= 0 or complete_at < window_end):
            _append_event(events, complete_at, "OBJECTIVE_COMPLETE")

        if first_zone is not None and current_grade and structural_grade and current_grade != structural_grade:
            observed_at = int(getattr(latest_analysis, "generated_at", 0) or row.get("last_seen_at") or 0)
            if observed_at and (window_end <= 0 or observed_at < window_end):
                _append_event(
                    events,
                    observed_at,
                    "GRADE_STATE_CHANGED",
                    structural_grade=structural_grade,
                    current_grade=current_grade,
                    reason=_note_text(latest_zone, "grade_degrade_reason:", "UNKNOWN"),
                )

        matched_feedback: list[dict] = []
        analysis_ids = {
            str(row.get("first_analysis_id") or ""),
            str(row.get("latest_analysis_id") or ""),
            str(row.get("ownership_analysis_id") or ""),
        }
        for item in feedback:
            ts = int(item.get("ts") or 0)
            if ts < published_at or (window_end > 0 and ts >= window_end):
                continue
            feedback_zone_id = str(item.get("zone_id") or "")
            feedback_analysis_id = str(item.get("analysis_id") or "")
            if feedback_zone_id:
                # Exact campaign attribution is authoritative. A trade belonging
                # to the BUY zone must never be projected onto a sibling SELL
                # publication merely because both zones existed in one analysis.
                if feedback_zone_id != zone_id:
                    continue
            elif feedback_analysis_id not in analysis_ids:
                # Legacy journal rows without zone_id may fall back to analysis
                # identity, but only when explicit zone provenance is absent.
                continue
            event = str(item.get("event") or "").upper()
            if event not in _TRADE_EVENTS:
                continue
            details = _json_obj(item.get("details"))
            matched_feedback.append(item)
            _append_event(
                events,
                ts,
                event,
                price=float(item.get("price") or 0.0),
                setup=str(details.get("setup") or details.get("setup_type") or ""),
                grade=str(details.get("grade") or ""),
                position_id=details.get("position_id"),
                deal_id=details.get("deal_id"),
                sequence_version=str(details.get("sequence_version") or ""),
            )
            setup = str(details.get("setup") or details.get("setup_type") or "").upper()
            if "FLIP" in setup and event in {"ENTRY_OPENED", "POSITION_MARK"}:
                _append_event(events, ts, "ACCEPTED_ZONE_FLIP_EXECUTION", setup=setup)

        events.sort(key=lambda item: (int(item.get("ts") or 0), str(item.get("event") or "")))

        lifecycle = str(row.get("lifecycle_status") or row.get("status") or "PUBLISHED")
        entry_count = sum(1 for x in matched_feedback if str(x.get("event") or "").upper() == "ENTRY_OPENED")
        closed_count = sum(1 for x in matched_feedback if str(x.get("event") or "").upper() == "TRADE_CLOSED")
        execution_state = "NO_ENTRY"
        if entry_count:
            execution_state = "CLOSED" if closed_count >= entry_count else "OPEN_OR_PARTIAL"

        if invalidated_at:
            outcome = "INVALIDATED_AFTER_REACTION" if reaction_ts and reaction_ts <= invalidated_at else "INVALIDATED_BEFORE_REACTION"
        elif complete_at:
            outcome = "OBJECTIVE_COMPLETE"
        elif any(int(row.get(f"target{i}_hit_at") or 0) for i in (1, 2, 3)):
            outcome = "OBJECTIVE_PROGRESS"
        elif reaction_ts:
            outcome = "REACTION_CONFIRMED"
        elif live_touch:
            outcome = "CONTACTED_WAITING_FOR_REACTION"
        else:
            outcome = "WAITING_FOR_CONTACT"

        output.append(
            {
                "publication_key": str(row.get("publication_key") or ""),
                "validation_sample_key": str(row.get("validation_sample_key") or ""),
                "publication_observation_count": int(row.get("publication_observation_count") or 1),
                "reaction_key": str(row.get("reaction_key") or ""),
                "zone_id": zone_id,
                "first_analysis_id": str(row.get("first_analysis_id") or ""),
                "latest_analysis_id": str(row.get("latest_analysis_id") or ""),
                "published_at": published_at,
                "last_seen_at": int(row.get("last_seen_at") or 0),
                "window_end": window_end,
                "direction": str(row.get("direction") or ""),
                "setup_type": str(getattr(first_zone, "setup_type", "") or ""),
                "source_tf": str(row.get("source_tf") or ""),
                "source_ts": int(row.get("source_ts") or 0),
                "core_low": float(row.get("core_low") or 0.0),
                "core_high": float(row.get("core_high") or 0.0),
                "zone_low": float(row.get("zone_low") or 0.0),
                "zone_high": float(row.get("zone_high") or 0.0),
                "structural_grade": structural_grade,
                "current_grade": current_grade,
                "qualified_mitigations": qualified,
                "raw_core_contacts": raw_contacts,
                "publication_qualified_mitigations": int(row.get("publication_qualified_mitigations") or 0),
                "publication_raw_core_contacts": int(row.get("publication_raw_core_contacts") or 0),
                "risk_context": risk_context,
                "base_risk_pct": base_risk,
                "live_core_touched_at": live_touch,
                "live_core_touch_basis": str(row.get("live_core_touch_basis") or ""),
                "lifecycle_status": lifecycle,
                "reaction_confirmed_at": reaction_ts,
                "handoff_at": handoff_ts,
                "handoff_authority": str(row.get("ownership_authority") or ""),
                "invalidation_at": invalidated_at,
                "objective_complete_at": complete_at,
                "best_price": float(row.get("best_price") or 0.0),
                "mfe_price": float(row.get("mfe_price") or 0.0),
                "execution_state": execution_state,
                "entry_count": entry_count,
                "closed_count": closed_count,
                "outcome": outcome,
                "events": events,
                "read_only": True,
            }
        )

    counts = Counter(row["outcome"] for row in output)
    by_direction: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_grade: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in output:
        by_direction[row["direction"]]["publications"] += 1
        by_direction[row["direction"]][row["outcome"]] += 1
        by_grade[row["structural_grade"] or "UNKNOWN"]["publications"] += 1
        by_grade[row["structural_grade"] or "UNKNOWN"][row["outcome"]] += 1

    contacted = sum(1 for row in output if row["live_core_touched_at"] > 0)
    reacted = sum(1 for row in output if row["reaction_confirmed_at"] > 0)
    reacted_after_contact = sum(
        1 for row in output
        if row["live_core_touched_at"] > 0
        and row["reaction_confirmed_at"] >= row["live_core_touched_at"] > 0
    )
    executed = sum(1 for row in output if row["entry_count"] > 0)
    executed_after_contact = sum(
        1 for row in output
        if row["live_core_touched_at"] > 0 and row["entry_count"] > 0
    )
    raw_publication_records = sum(int(row.get("publication_observation_count") or 1) for row in output)
    summary = {
        "publications": len(output),
        "raw_publication_records": raw_publication_records,
        "live_contacts": contacted,
        "reaction_confirmed": reacted,
        "reaction_confirmed_after_live_contact": reacted_after_contact,
        "reaction_confirmed_without_live_core_contact": max(0, reacted - reacted_after_contact),
        "invalidated_before_reaction": counts.get("INVALIDATED_BEFORE_REACTION", 0),
        "invalidated_after_reaction": counts.get("INVALIDATED_AFTER_REACTION", 0),
        "objective_complete": counts.get("OBJECTIVE_COMPLETE", 0),
        "objective_progress": counts.get("OBJECTIVE_PROGRESS", 0),
        "executed_publications": executed,
        "reaction_rate_after_contact_pct": round(100.0 * reacted_after_contact / contacted, 1) if contacted else None,
        "execution_rate_after_contact_pct": round(100.0 * executed_after_contact / contacted, 1) if contacted else None,
        "by_direction": {key: dict(value) for key, value in by_direction.items()},
        "by_structural_grade": {key: dict(value) for key, value in by_grade.items()},
    }
    return {
        "contract": VALIDATION_LEDGER_VERSION,
        "paper_only": True,
        "read_only": True,
        "authority": "OBSERVATION_ONLY_NO_EXECUTION_EFFECT",
        "summary": summary,
        "rows": output,
    }


def export_validation_csv(limit: int = 250) -> str:
    data = build_validation_ledger(limit)
    out = io.StringIO()
    fields = [
        "published_at","zone_id","direction","source_tf","setup_type",
        "structural_grade","current_grade","core_low","core_high","zone_low","zone_high",
        "publication_qualified_mitigations","qualified_mitigations","raw_core_contacts",
        "risk_context","base_risk_pct","live_core_touched_at","reaction_confirmed_at",
        "handoff_at","handoff_authority","invalidation_at","objective_complete_at",
        "execution_state","entry_count","closed_count","outcome",
    ]
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in data.get("rows", []):
        writer.writerow(row)
    return out.getvalue()
