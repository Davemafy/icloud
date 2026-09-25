from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from .db import connect
from .models import Analysis, Zone
from .risk_matrix import original_risk_pct, zone_risk_context
from .zone_publication_migration import ensure_zone_publication_schema
from .execution_ownership_migration import ensure_execution_ownership_schema


VALIDATION_LEDGER_VERSION = "MASTER_SNIPER_VALIDATION_LEDGER_V1"
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


def _publication_rows(limit: int) -> list[dict]:
    ensure_execution_ownership_schema()
    ensure_zone_publication_schema()
    limit = max(1, min(int(limit), 250))
    with connect() as db:
        rows = db.execute(
            """
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
            LEFT JOIN zone_reactions r ON r.reaction_key=p.reaction_key
            ORDER BY p.first_published_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


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
                "live_contacts": 0,
                "reaction_confirmed": 0,
                "invalidated_before_reaction": 0,
                "invalidated_after_reaction": 0,
                "objective_complete": 0,
                "executed_publications": 0,
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
            if str(item.get("zone_id") or "") != zone_id and str(item.get("analysis_id") or "") not in analysis_ids:
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
    executed = sum(1 for row in output if row["entry_count"] > 0)
    summary = {
        "publications": len(output),
        "live_contacts": contacted,
        "reaction_confirmed": reacted,
        "invalidated_before_reaction": counts.get("INVALIDATED_BEFORE_REACTION", 0),
        "invalidated_after_reaction": counts.get("INVALIDATED_AFTER_REACTION", 0),
        "objective_complete": counts.get("OBJECTIVE_COMPLETE", 0),
        "objective_progress": counts.get("OBJECTIVE_PROGRESS", 0),
        "executed_publications": executed,
        "reaction_rate_after_contact_pct": round(100.0 * reacted / contacted, 1) if contacted else None,
        "execution_rate_after_contact_pct": round(100.0 * executed / contacted, 1) if contacted else None,
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
