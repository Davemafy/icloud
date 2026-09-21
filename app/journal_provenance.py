from __future__ import annotations

"""Journal provenance + execution aggregation.

This module is intentionally read-only. It reconciles MT5 lifecycle telemetry into
position records and conservative execution groups without changing plan selection,
risk, orders, or Sequence EA state.
"""

import csv
import io
from datetime import datetime, timezone
from typing import Any

from .config import SETTINGS
from . import journal as base_journal


_TRADE_EVENTS = {
    "ENTRY_OPENED",
    "POSITION_MARK",
    "POSITION_EXIT",
    "TP_HIT",
    "SL_HIT",
    "TRADE_CLOSED",
}

_SETUP_BY_TAG = {
    "P0": "PRIMARY",
    "R1": "REENTRY_1",
    "R2": "REENTRY_2",
    "F0": "ZONE_FLIP",
    "FR1": "FLIP_REENTRY_1",
    "FR2": "FLIP_REENTRY_2",
    "S0": "ZONE_SWEEP_CONTINUATION",
    "L0": "LIQUIDITY_REVERSAL",
    "C0": "CONTINUATION_RESCUE",
    "E0": "ESCAPE_PULLBACK",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _placeholder_analysis(value: Any) -> bool:
    v = _clean(value).upper()
    return not v or v in {"MT5_HISTORY", "NO_ANALYSIS"}


def _placeholder_zone(value: Any) -> bool:
    v = _clean(value).upper()
    return not v or v in {"NO_ZONE", "NONE"}


def _meaningful_campaign(value: Any) -> bool:
    v = _clean(value)
    u = v.upper()
    if not v:
        return False
    if u.startswith("MT5_HISTORY|") or u.startswith("MT5POS|"):
        return False
    if "NO_ANALYSIS" in u or "NO_ZONE" in u or u.endswith("|UNKNOWN"):
        return False
    return True


def _setup_candidate(details: dict) -> tuple[str, str, int]:
    explicit = _clean(details.get("setup"))
    if explicit and explicit.upper() != "UNKNOWN":
        return explicit, _clean(details.get("metadata_source")) or "EVENT_SETUP", 4

    tag = _clean(details.get("tag")).upper()
    if tag in _SETUP_BY_TAG:
        src = _clean(details.get("metadata_source")) or "MT5_TAG"
        return _SETUP_BY_TAG[tag], src, 3

    comment = _clean(details.get("comment")).upper()
    padded = f" {comment} "
    for candidate in sorted(_SETUP_BY_TAG, key=len, reverse=True):
        if f" {candidate} " in padded or comment.startswith(candidate + " "):
            return _SETUP_BY_TAG[candidate], "MT5_COMMENT", 2

    return "UNKNOWN", "UNAVAILABLE", 0


def _event_identity(row: dict, details: dict, event: str) -> str:
    explicit = _clean(details.get("event_uid"))
    if explicit:
        return explicit
    deal_id = details.get("deal_id")
    if deal_id not in (None, "", 0, "0"):
        return f"{event}|DEAL|{deal_id}"
    position_id = details.get("position_id")
    if event == "TRADE_CLOSED" and position_id not in (None, "", 0, "0"):
        return f"{event}|POSITION|{position_id}"
    return ""


def _position_key(row: dict, details: dict, setup: str) -> str:
    position_id = details.get("position_id")
    if position_id not in (None, "", 0, "0"):
        return f"POSITION:{position_id}"
    raw_trade_id = _clean(details.get("trade_id"))
    if raw_trade_id:
        return raw_trade_id
    return "|".join(
        [
            _clean(row.get("analysis_id")) or "NO_ANALYSIS",
            _clean(row.get("zone_id")) or "NO_ZONE",
            setup if setup != "UNKNOWN" else "EXECUTION",
        ]
    )


def _trusted_execution_context(event: str, details: dict, recovered: bool) -> bool:
    """Whether this event can describe the ORIGINAL execution context.

    Current POSITION_MARK telemetry may legitimately describe the current owner,
    cloud and runtime after a reload. It must not be retroactively promoted into
    original entry provenance.
    """
    source = _clean(details.get("metadata_source")).upper()
    if source in {"LIVE_ENTRY_CONTEXT", "LOCAL_POSITION_METADATA"}:
        return True
    return event == "ENTRY_OPENED" and not recovered


def _apply_versions(group: dict, details: dict, recovered: bool, event: str) -> None:
    if recovered:
        rb = _clean(details.get("recovery_bridge_version") or details.get("bridge_version"))
        rs = _clean(details.get("recovery_sequence_version") or details.get("sequence_version"))
        rc = _clean(details.get("recovery_cloud_version"))
        if rb:
            group["recovery_bridge_version"] = rb
        if rs:
            group["recovery_sequence_version"] = rs
        if rc:
            group["recovery_cloud_version"] = rc
        if rb or rs or rc:
            group["recovery_version_provenance"] = "MT5_HISTORY_REPLAY"

    if not _trusted_execution_context(event, details, recovered):
        return

    if recovered:
        eb = _clean(details.get("execution_bridge_version"))
        es = _clean(details.get("execution_sequence_version"))
        ec = _clean(details.get("execution_cloud_version"))
    else:
        eb = _clean(details.get("execution_bridge_version") or details.get("bridge_version"))
        es = _clean(details.get("execution_sequence_version") or details.get("sequence_version"))
        ec = _clean(details.get("execution_cloud_version") or details.get("cloud_version"))

    wrote = False
    if eb and not _clean(group.get("execution_bridge_version")):
        group["execution_bridge_version"] = eb
        wrote = True
    if es and not _clean(group.get("execution_sequence_version")):
        group["execution_sequence_version"] = es
        wrote = True
    if ec and not _clean(group.get("execution_cloud_version")):
        group["execution_cloud_version"] = ec
        wrote = True
    if wrote and _clean(group.get("execution_version_provenance")) in {"", "UNAVAILABLE"}:
        group["execution_version_provenance"] = (
            _clean(details.get("metadata_source")) or ("LOCAL_POSITION_METADATA" if recovered else "LIVE_ENTRY")
        )


def _known_setup(value: Any) -> bool:
    return _clean(value).upper() not in {"", "UNKNOWN", "UNCLASSIFIED_HISTORY"}


def _known_grade(value: Any) -> bool:
    return _clean(value).upper() not in {"", "UNKNOWN", "UNCLASSIFIED_HISTORY"}


def build_trades(limit_events: int = 5000) -> list[dict]:
    """Build canonical MT5 position records with explicit provenance.

    A replayed history event may fill lifecycle facts, but it is never allowed to
    overwrite stronger live setup/version metadata with UNKNOWN/current recovery
    runtime values.
    """
    rows = sorted(
        base_journal.recent_feedback(limit_events),
        key=lambda row: (int(row.get("ts") or 0), int(row.get("id") or 0)),
    )
    groups: dict[str, dict] = {}
    seen_event_ids: set[str] = set()

    for row in rows:
        event = _clean(row.get("event")).upper()
        if event not in _TRADE_EVENTS:
            continue

        details = base_journal.parse_details(row.get("details"))
        recovered = bool(details.get("recovered_from_mt5_history"))
        trusted_context = _trusted_execution_context(event, details, recovered)
        setup, setup_source, setup_rank = _setup_candidate(details)
        position_id = details.get("position_id")
        raw_trade_id = _clean(details.get("trade_id"))
        campaign = _clean(details.get("campaign_id"))
        event_uid = _event_identity(row, details, event)
        if event_uid:
            if event_uid in seen_event_ids:
                continue
            seen_event_ids.add(event_uid)

        key = _position_key(row, details, setup)
        group = groups.setdefault(
            key,
            {
                "trade_id": raw_trade_id or key,
                "campaign_id": (
                    campaign
                    if trusted_context and _meaningful_campaign(campaign)
                    else raw_trade_id
                    if trusted_context and _meaningful_campaign(raw_trade_id)
                    else ""
                ),
                "execution_id": "",
                "execution_group_provenance": "",
                "display_id": "",
                "position_id": position_id,
                "analysis_id": _clean(row.get("analysis_id")) if trusted_context else ("MT5_HISTORY" if recovered else ""),
                "zone_id": _clean(row.get("zone_id")) if trusted_context else "",
                "setup": setup,
                "setup_provenance": setup_source,
                "grade": _clean(details.get("grade")) if trusted_context else "",
                "grade_provenance": (
                    _clean(details.get("metadata_source")) or ("MT5_HISTORY" if recovered else "LIVE_EVENT")
                ) if trusted_context and _clean(details.get("grade")) else "UNAVAILABLE",
                "direction": _clean(details.get("direction")),
                "status": "OPEN" if event == "POSITION_MARK" else "PLANNED",
                "entry_ts": None,
                "exit_ts": None,
                "entry_price": None,
                "exit_price": None,
                "volume": details.get("volume"),
                "pnl": 0.0,
                "r_multiple": None,
                "mfe_r": None,
                "mae_r": None,
                "history_recovered": recovered,
                "execution_bridge_version": "",
                "execution_sequence_version": "",
                "execution_cloud_version": "",
                "execution_version_provenance": "UNAVAILABLE",
                "recovery_bridge_version": "",
                "recovery_sequence_version": "",
                "recovery_cloud_version": "",
                "recovery_version_provenance": "UNAVAILABLE",
                "event_count": 0,
                "last_event": "",
                "last_ts": int(row.get("ts") or 0),
                "_setup_rank": setup_rank,
            },
        )

        ts = int(row.get("ts") or 0)
        price = float(row.get("price") or 0.0)
        group["event_count"] += 1
        group["last_event"] = event
        group["last_ts"] = ts
        group["history_recovered"] = bool(group.get("history_recovered") or recovered)

        if setup_rank > int(group.get("_setup_rank") or 0):
            group["setup"] = setup
            group["setup_provenance"] = setup_source
            group["_setup_rank"] = setup_rank

        candidate_grade = _clean(details.get("grade"))
        if trusted_context and candidate_grade and (
            not _known_grade(group.get("grade"))
            or _clean(details.get("metadata_source")) == "LOCAL_POSITION_METADATA"
        ):
            group["grade"] = candidate_grade
            group["grade_provenance"] = _clean(details.get("metadata_source")) or (
                "MT5_HISTORY" if recovered else "LIVE_EVENT"
            )

        candidate_analysis = _clean(row.get("analysis_id"))
        if trusted_context and _placeholder_analysis(group.get("analysis_id")) and not _placeholder_analysis(candidate_analysis):
            group["analysis_id"] = candidate_analysis
        candidate_zone = _clean(row.get("zone_id"))
        if trusted_context and _placeholder_zone(group.get("zone_id")) and not _placeholder_zone(candidate_zone):
            group["zone_id"] = candidate_zone

        if trusted_context and _meaningful_campaign(campaign) and not _meaningful_campaign(group.get("campaign_id")):
            group["campaign_id"] = campaign
        elif trusted_context and _meaningful_campaign(raw_trade_id) and not _meaningful_campaign(group.get("campaign_id")):
            group["campaign_id"] = raw_trade_id

        if raw_trade_id and raw_trade_id.upper().startswith("MT5POS|"):
            group["trade_id"] = raw_trade_id
        elif raw_trade_id and not _clean(group.get("trade_id")):
            group["trade_id"] = raw_trade_id

        if _clean(details.get("direction")):
            group["direction"] = _clean(details.get("direction"))
        if details.get("volume") is not None:
            group["volume"] = details.get("volume")
        if position_id not in (None, "", 0, "0"):
            group["position_id"] = position_id

        _apply_versions(group, details, recovered, event)

        if event == "ENTRY_OPENED":
            if group["status"] != "CLOSED":
                group["status"] = "OPEN"
            group["entry_ts"] = group["entry_ts"] or ts
            group["entry_price"] = group["entry_price"] or price
        elif event == "POSITION_MARK":
            if group["status"] not in {"CLOSED", "MANAGING"}:
                group["status"] = "OPEN"
            if group["entry_price"] is None and details.get("entry_price") is not None:
                group["entry_price"] = float(details.get("entry_price") or 0.0) or None
            if group["entry_ts"] is None:
                group["entry_ts"] = ts
        elif event in {"POSITION_EXIT", "TP_HIT", "SL_HIT"}:
            if group["status"] != "CLOSED":
                group["status"] = "MANAGING"
            group["exit_price"] = price or group["exit_price"]
            group["pnl"] += float(details.get("net_profit") or 0.0)
        elif event == "TRADE_CLOSED":
            group["status"] = "CLOSED"
            group["exit_ts"] = ts
            group["exit_price"] = price or group["exit_price"]

        if details.get("r_multiple") is not None:
            r_value = float(details["r_multiple"])
            group["mfe_r"] = r_value if group["mfe_r"] is None else max(group["mfe_r"], r_value)
            group["mae_r"] = r_value if group["mae_r"] is None else min(group["mae_r"], r_value)

    position_campaigns = {
        _clean(g.get("campaign_id"))
        for g in groups.values()
        if g.get("position_id") not in (None, "", 0, "0") and _meaningful_campaign(g.get("campaign_id"))
    }
    positions = [
        g
        for g in groups.values()
        if not (
            g.get("position_id") in (None, "", 0, "0")
            and (
                _clean(g.get("campaign_id"))
                if _meaningful_campaign(g.get("campaign_id"))
                else _clean(g.get("trade_id"))
                if _meaningful_campaign(g.get("trade_id"))
                else ""
            ) in position_campaigns
            and _clean(g.get("status")).upper() == "CLOSED"
        )
    ]

    for g in positions:
        if not _known_setup(g.get("setup")):
            g["setup"] = "UNCLASSIFIED_HISTORY" if g.get("history_recovered") else "UNKNOWN"
            if g.get("history_recovered"):
                g["setup_provenance"] = "UNAVAILABLE_FROM_MT5_HISTORY"
        if not _known_grade(g.get("grade")) and g.get("history_recovered"):
            g["grade"] = "UNCLASSIFIED_HISTORY"
            g["grade_provenance"] = "UNAVAILABLE_FROM_MT5_HISTORY"
        pid = g.get("position_id")
        g["display_id"] = (
            f"{g.get('setup') or 'TRADE'} · POS {pid}"
            if pid not in (None, "", 0, "0")
            else (g.get("setup") or "TRADE")
        )
        g.pop("_setup_rank", None)

    _annotate_execution_groups(positions)
    return list(reversed(positions))


def _price_close(a: Any, b: Any, tolerance: float = 0.35) -> bool:
    try:
        return abs(float(a) - float(b)) <= tolerance
    except (TypeError, ValueError):
        return False


def _setup_compatible(a: dict, b: dict) -> bool:
    sa, sb = _clean(a.get("setup")), _clean(b.get("setup"))
    if _known_setup(sa) and _known_setup(sb):
        return sa == sb
    return True


def _annotate_execution_groups(positions: list[dict]) -> list[dict]:
    ordered = sorted(
        positions,
        key=lambda row: (int(row.get("entry_ts") or row.get("last_ts") or 0), str(row.get("position_id") or "")),
    )
    buckets: list[dict] = []

    for row in ordered:
        campaign = _clean(row.get("campaign_id"))
        if _meaningful_campaign(campaign):
            key = "CAMPAIGN:" + campaign
            bucket = next((b for b in buckets if b["key"] == key), None)
            if bucket is None:
                bucket = {
                    "key": key,
                    "provenance": "EXACT_CAMPAIGN",
                    "anchor_ts": int(row.get("entry_ts") or row.get("last_ts") or 0),
                    "anchor_price": row.get("entry_price"),
                    "direction": _clean(row.get("direction")),
                    "rows": [],
                }
                buckets.append(bucket)
            bucket["rows"].append(row)
            continue

        entry_ts = int(row.get("entry_ts") or row.get("last_ts") or 0)
        direction = _clean(row.get("direction"))
        candidate = None
        for bucket in reversed(buckets):
            if direction != bucket["direction"]:
                continue
            if abs(entry_ts - int(bucket["anchor_ts"])) > 2:
                continue
            if not _price_close(row.get("entry_price"), bucket.get("anchor_price")):
                continue
            if bucket["rows"] and not _setup_compatible(row, bucket["rows"][0]):
                continue
            candidate = bucket
            break

        if candidate is None:
            key = f"BURST:{direction or 'UNKNOWN'}:{entry_ts}:{float(row.get('entry_price') or 0.0):.2f}"
            candidate = {
                "key": key,
                "provenance": "SINGLE_POSITION",
                "anchor_ts": entry_ts,
                "anchor_price": row.get("entry_price"),
                "direction": direction,
                "rows": [],
            }
            buckets.append(candidate)
        else:
            candidate["provenance"] = (
                "CAMPAIGN_ASSISTED_BURST"
                if candidate["provenance"] == "EXACT_CAMPAIGN"
                else "RECONSTRUCTED_ENTRY_BURST"
            )
        candidate["rows"].append(row)

    for bucket in buckets:
        rows = bucket["rows"]
        campaign_values = {_clean(r.get("campaign_id")) for r in rows if _meaningful_campaign(r.get("campaign_id"))}
        setup_values = {_clean(r.get("setup")) for r in rows if _known_setup(r.get("setup"))}
        grade_values = {_clean(r.get("grade")) for r in rows if _known_grade(r.get("grade"))}
        analysis_values = {_clean(r.get("analysis_id")) for r in rows if not _placeholder_analysis(r.get("analysis_id"))}
        zone_values = {_clean(r.get("zone_id")) for r in rows if not _placeholder_zone(r.get("zone_id"))}
        version_sets = {
            field: {_clean(r.get(field)) for r in rows if _clean(r.get(field))}
            for field in ("execution_bridge_version", "execution_sequence_version", "execution_cloud_version")
        }

        for row in rows:
            row["execution_id"] = bucket["key"]
            row["execution_group_provenance"] = bucket["provenance"]
            if not _meaningful_campaign(row.get("campaign_id")) and len(campaign_values) == 1:
                row["campaign_id"] = next(iter(campaign_values))
            if not _known_setup(row.get("setup")) and len(setup_values) == 1:
                row["setup"] = next(iter(setup_values))
                row["setup_provenance"] = "EXECUTION_GROUP_INHERITANCE"
            if not _known_grade(row.get("grade")) and len(grade_values) == 1:
                row["grade"] = next(iter(grade_values))
                row["grade_provenance"] = "EXECUTION_GROUP_INHERITANCE"
            if _placeholder_analysis(row.get("analysis_id")) and len(analysis_values) == 1:
                row["analysis_id"] = next(iter(analysis_values))
            if _placeholder_zone(row.get("zone_id")) and len(zone_values) == 1:
                row["zone_id"] = next(iter(zone_values))
            for field, values in version_sets.items():
                if not _clean(row.get(field)) and len(values) == 1:
                    row[field] = next(iter(values))
                    row["execution_version_provenance"] = "EXECUTION_GROUP_INHERITANCE"

            pid = row.get("position_id")
            row["display_id"] = (
                f"{row.get('setup') or 'TRADE'} · POS {pid}"
                if pid not in (None, "", 0, "0")
                else (row.get("setup") or "TRADE")
            )

    return positions


def build_execution_groups(positions: list[dict] | None = None) -> list[dict]:
    positions = list(positions if positions is not None else build_trades())
    if positions and not _clean(positions[0].get("execution_id")):
        _annotate_execution_groups(positions)

    grouped: dict[str, list[dict]] = {}
    for row in positions:
        grouped.setdefault(_clean(row.get("execution_id")) or _clean(row.get("trade_id")), []).append(row)

    out: list[dict] = []
    for execution_id, rows in grouped.items():
        statuses = {_clean(r.get("status")).upper() for r in rows}
        if statuses == {"CLOSED"}:
            status = "CLOSED"
        elif "MANAGING" in statuses:
            status = "MANAGING"
        elif "OPEN" in statuses:
            status = "OPEN"
        else:
            status = "PLANNED"

        setups = {_clean(r.get("setup")) for r in rows if _known_setup(r.get("setup"))}
        grades = {_clean(r.get("grade")) for r in rows if _known_grade(r.get("grade"))}
        directions = {_clean(r.get("direction")) for r in rows if _clean(r.get("direction"))}
        entry_times = [int(r.get("entry_ts") or 0) for r in rows if int(r.get("entry_ts") or 0) > 0]
        exit_times = [int(r.get("exit_ts") or 0) for r in rows if int(r.get("exit_ts") or 0) > 0]
        volumes = [float(r.get("volume") or 0.0) for r in rows]
        total_volume = sum(v for v in volumes if v > 0)
        if total_volume > 0:
            entry_price = sum(float(r.get("entry_price") or 0.0) * max(float(r.get("volume") or 0.0), 0.0) for r in rows) / total_volume
        else:
            priced = [float(r.get("entry_price") or 0.0) for r in rows if r.get("entry_price") is not None]
            entry_price = sum(priced) / len(priced) if priced else None

        out.append(
            {
                "execution_id": execution_id,
                "grouping_provenance": _clean(rows[0].get("execution_group_provenance")) or "SINGLE_POSITION",
                "position_count": len(rows),
                "position_ids": [r.get("position_id") for r in rows if r.get("position_id") not in (None, "", 0, "0")],
                "campaign_id": next((_clean(r.get("campaign_id")) for r in rows if _meaningful_campaign(r.get("campaign_id"))), ""),
                "analysis_id": next((_clean(r.get("analysis_id")) for r in rows if not _placeholder_analysis(r.get("analysis_id"))), ""),
                "zone_id": next((_clean(r.get("zone_id")) for r in rows if not _placeholder_zone(r.get("zone_id"))), ""),
                "setup": next(iter(setups)) if len(setups) == 1 else ("MIXED" if setups else "UNCLASSIFIED_HISTORY"),
                "grade": next(iter(grades)) if len(grades) == 1 else ("MIXED" if grades else "UNCLASSIFIED_HISTORY"),
                "direction": next(iter(directions)) if len(directions) == 1 else ("MIXED" if directions else ""),
                "status": status,
                "entry_ts": min(entry_times) if entry_times else None,
                "exit_ts": max(exit_times) if exit_times else None,
                "entry_price": entry_price,
                "pnl": sum(float(r.get("pnl") or 0.0) for r in rows),
                "history_recovered": any(bool(r.get("history_recovered")) for r in rows),
            }
        )

    return sorted(out, key=lambda row: int(row.get("entry_ts") or 0), reverse=True)


def _bucket_summary(rows: list[dict], key: str) -> dict:
    out: dict[str, dict] = {}
    for row in rows:
        raw_name = _clean(row.get(key)) or "UNKNOWN"
        name = "Unclassified (history-only)" if raw_name == "UNCLASSIFIED_HISTORY" else raw_name
        bucket = out.setdefault(name, {"executions": 0, "trades": 0, "wins": 0, "net_demo_pnl": 0.0})
        bucket["executions"] += 1
        bucket["trades"] += 1  # compatibility for older dashboard clients
        pnl = float(row.get("pnl") or 0.0)
        bucket["net_demo_pnl"] += pnl
        if pnl > 0:
            bucket["wins"] += 1
    for bucket in out.values():
        bucket["win_rate"] = (
            bucket["wins"] / bucket["executions"] * 100.0 if bucket["executions"] else 0.0
        )
    return out


def performance_summary() -> dict:
    positions = build_trades()
    executions = build_execution_groups(positions)
    closed_positions = [x for x in positions if x.get("status") == "CLOSED"]
    closed_executions = [x for x in executions if x.get("status") == "CLOSED"]
    wins = [x for x in closed_executions if float(x.get("pnl") or 0.0) > 0]
    now = int(datetime.now(timezone.utc).timestamp())
    last_7d_exec = [x for x in closed_executions if int(x.get("exit_ts") or 0) >= now - 7 * 86400]
    last_7d_positions = [x for x in closed_positions if int(x.get("exit_ts") or 0) >= now - 7 * 86400]

    observations = [
        x for x in base_journal.recent_feedback(5000)
        if _clean(x.get("event")).upper() == "ML_CANDIDATE"
    ]
    unique_observations = {
        _clean(base_journal.parse_details(row.get("details")).get("candidate_id"))
        for row in observations
        if _clean(base_journal.parse_details(row.get("details")).get("candidate_id"))
    }

    closed_execution_pnl = sum(float(x.get("pnl") or 0.0) for x in closed_executions)
    realized_position_pnl = sum(float(x.get("pnl") or 0.0) for x in closed_positions)
    return {
        "paper_only": SETTINGS.paper_only,
        "aggregation_basis": "EXECUTION_GROUP",
        "grouping_policy": (
            "Exact campaign IDs when available; otherwise only same-direction entries within 2 seconds "
            "and 0.35 XAU price units are grouped as one reconstructed execution burst. "
            "Win rate waits for the whole execution group to close; Demo P/L includes realized closed MT5 legs."
        ),
        "execution_count": len(executions),
        "closed_executions": len(closed_executions),
        "execution_wins": len(wins),
        "execution_win_rate": (len(wins) / len(closed_executions) * 100.0) if closed_executions else None,
        "position_count": len(positions),
        "closed_positions": len(closed_positions),
        "trade_count": len(executions),  # compatibility: now means grouped executions
        "closed_trades": len(closed_executions),
        "wins": len(wins),
        "win_rate": (len(wins) / len(closed_executions) * 100.0) if closed_executions else None,
        "net_demo_pnl": realized_position_pnl,
        "realized_position_pnl": realized_position_pnl,
        "closed_execution_pnl": closed_execution_pnl,
        "research_observations": len(observations),
        "unique_research_observations": len(unique_observations),
        "last_7d": {
            "closed_executions": len(last_7d_exec),
            "closed_positions": len(last_7d_positions),
            "closed_trades": len(last_7d_exec),
            "net_demo_pnl": sum(float(x.get("pnl") or 0.0) for x in last_7d_positions),
        },
        "by_setup": _bucket_summary(closed_executions, "setup"),
        "by_direction": _bucket_summary(closed_executions, "direction"),
        "by_grade": _bucket_summary(closed_executions, "grade"),
    }


def export_csv_text() -> str:
    rows = build_trades()
    cols = [
        "trade_id",
        "execution_id",
        "execution_group_provenance",
        "campaign_id",
        "display_id",
        "position_id",
        "analysis_id",
        "zone_id",
        "setup",
        "setup_provenance",
        "direction",
        "grade",
        "grade_provenance",
        "status",
        "entry_ts",
        "exit_ts",
        "entry_price",
        "exit_price",
        "volume",
        "pnl",
        "mfe_r",
        "mae_r",
        "history_recovered",
        "execution_cloud_version",
        "execution_bridge_version",
        "execution_sequence_version",
        "execution_version_provenance",
        "recovery_cloud_version",
        "recovery_bridge_version",
        "recovery_sequence_version",
        "recovery_version_provenance",
        "last_event",
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return out.getvalue()
