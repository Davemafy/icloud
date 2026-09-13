from __future__ import annotations

"""Read-only DEMO/PAPER journal, component health and update-state aggregation."""

import csv
import io
import json
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .config import SETTINGS
from .db import recent_feedback, latest_heartbeats, latest_snapshot
from .ml_foundation import ml_status

_STABLE_URL = "https://raw.githubusercontent.com/Davemafy/icloud/main/mt5/stable/manifest.json"
_manifest_cache: dict[str, Any] = {"at": 0.0, "value": None}


def parse_details(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    text = str(raw).strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {"value": obj}
    except Exception:
        return {"text": text}


def build_trades(limit_events: int = 5000) -> list[dict]:
    rows = list(reversed(recent_feedback(limit_events)))
    groups: dict[str, dict] = {}
    for row in rows:
        d = parse_details(row.get("details"))
        key = str(
            d.get("trade_id")
            or "|".join(
                [
                    str(row.get("analysis_id") or "NO_ANALYSIS"),
                    str(row.get("zone_id") or "NO_ZONE"),
                    str(d.get("setup") or "NO_SETUP"),
                ]
            )
        )
        g = groups.setdefault(
            key,
            {
                "trade_id": key,
                "analysis_id": row.get("analysis_id") or "",
                "zone_id": row.get("zone_id") or "",
                "setup": d.get("setup") or "",
                "direction": d.get("direction") or "",
                "grade": d.get("grade") or "",
                "status": "PLANNED",
                "entry_ts": None,
                "exit_ts": None,
                "entry_price": None,
                "exit_price": None,
                "pnl": 0.0,
                "r_multiple": None,
                "mfe_r": None,
                "mae_r": None,
                "bridge_version": d.get("bridge_version") or "",
                "sequence_version": d.get("sequence_version") or "",
                "cloud_version": SETTINGS.app_version,
                "event_count": 0,
                "last_event": "",
                "last_ts": row.get("ts"),
            },
        )
        event = str(row.get("event") or "").upper()
        ts = int(row.get("ts") or 0)
        price = float(row.get("price") or 0.0)
        g["event_count"] += 1
        g["last_event"] = event
        g["last_ts"] = ts
        if d.get("setup"):
            g["setup"] = d["setup"]
        if d.get("direction"):
            g["direction"] = d["direction"]
        if d.get("grade"):
            g["grade"] = d["grade"]
        if d.get("bridge_version"):
            g["bridge_version"] = d["bridge_version"]
        if d.get("sequence_version"):
            g["sequence_version"] = d["sequence_version"]

        if event == "ENTRY_OPENED":
            g["status"] = "OPEN"
            g["entry_ts"] = g["entry_ts"] or ts
            g["entry_price"] = g["entry_price"] or price
        elif event in {"POSITION_EXIT", "TP_HIT", "SL_HIT"}:
            g["status"] = "MANAGING"
            g["exit_price"] = price or g["exit_price"]
            g["pnl"] += float(d.get("net_profit") or 0.0)
        elif event == "TRADE_CLOSED":
            g["status"] = "CLOSED"
            g["exit_ts"] = ts
            g["exit_price"] = price or g["exit_price"]

        if d.get("r_multiple") is not None:
            r = float(d["r_multiple"])
            g["mfe_r"] = r if g["mfe_r"] is None else max(g["mfe_r"], r)
            g["mae_r"] = r if g["mae_r"] is None else min(g["mae_r"], r)

    return list(reversed(list(groups.values())))


def _bucket_summary(rows: list[dict], key: str) -> dict:
    out: dict[str, dict] = {}
    for row in rows:
        name = str(row.get(key) or "UNKNOWN")
        b = out.setdefault(name, {"trades": 0, "wins": 0, "net_demo_pnl": 0.0})
        b["trades"] += 1
        pnl = float(row.get("pnl") or 0.0)
        b["net_demo_pnl"] += pnl
        if pnl > 0:
            b["wins"] += 1
    for b in out.values():
        b["win_rate"] = (b["wins"] / b["trades"] * 100.0) if b["trades"] else 0.0
    return out


def performance_summary() -> dict:
    trades = build_trades()
    closed = [x for x in trades if x.get("status") == "CLOSED"]
    wins = [x for x in closed if float(x.get("pnl") or 0.0) > 0]
    now = int(datetime.now(timezone.utc).timestamp())
    last_7d = [x for x in closed if int(x.get("exit_ts") or 0) >= now - 7 * 86400]
    return {
        "paper_only": SETTINGS.paper_only,
        "trade_count": len(trades),
        "closed_trades": len(closed),
        "wins": len(wins),
        "win_rate": (len(wins) / len(closed) * 100.0) if closed else 0.0,
        "net_demo_pnl": sum(float(x.get("pnl") or 0.0) for x in closed),
        "last_7d": {
            "closed_trades": len(last_7d),
            "net_demo_pnl": sum(float(x.get("pnl") or 0.0) for x in last_7d),
        },
        "by_setup": _bucket_summary(closed, "setup"),
        "by_direction": _bucket_summary(closed, "direction"),
        "by_grade": _bucket_summary(closed, "grade"),
    }


def _stable_manifest() -> dict:
    now = time.time()
    cached = _manifest_cache.get("value")
    if cached and now - float(_manifest_cache.get("at") or 0.0) < 30:
        return cached
    try:
        req = urllib.request.Request(_STABLE_URL, headers={"User-Agent": "TradeZoneCloud/6.4"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            value = json.loads(resp.read().decode("utf-8"))
        if isinstance(value, dict):
            _manifest_cache["at"] = now
            _manifest_cache["value"] = value
            return value
    except Exception:
        pass
    return cached or {}


def _hb_details(row: dict | None) -> dict:
    if not row:
        return {}
    payload = row.get("payload")
    if isinstance(payload, dict):
        d = payload.get("details")
        return d if isinstance(d, dict) else {}
    return {}


def _latest_hb(rows: list[dict], ea_name: str) -> dict | None:
    for row in rows:
        if str(row.get("ea") or "") == ea_name:
            return row
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _component_state(desired: str, installed: str, running: str, hb_age: int | None) -> str:
    if hb_age is None or hb_age > 180:
        return "OFFLINE"
    if desired and installed and installed != desired:
        return "UPDATE_PENDING"
    if desired and running and running != desired:
        return "RESTART_REQUIRED"
    if desired and not installed:
        if running == desired:
            return "CURRENT"
        return "INSTALL_STATUS_UNKNOWN"
    if desired and running == desired:
        return "CURRENT"
    return "UNKNOWN"


def component_status() -> dict:
    now = int(datetime.now(timezone.utc).timestamp())
    rows = latest_heartbeats(50)
    bridge_hb = _latest_hb(rows, "InstitutionalSMC_DataBridge")
    seq_hb = _latest_hb(rows, "InstitutionalSMC_SequenceEA")
    bridge_d = _hb_details(bridge_hb)
    seq_d = _hb_details(seq_hb)

    manifest = _stable_manifest()
    desired_bridge = str(manifest.get("data_bridge_version") or bridge_d.get("desired_bridge_version") or seq_d.get("desired_bridge_version") or "")
    desired_seq = str(manifest.get("sequence_ea_version") or bridge_d.get("desired_sequence_version") or seq_d.get("desired_sequence_version") or "")
    release = str(manifest.get("release") or bridge_d.get("stable_release") or seq_d.get("stable_release") or "")

    telemetry = bridge_d if bridge_d.get("updater_version") else seq_d
    installed_bridge = str(telemetry.get("installed_bridge_version") or "")
    installed_seq = str(telemetry.get("installed_sequence_version") or "")
    updater_version = str(telemetry.get("updater_version") or "")
    update_result = str(telemetry.get("update_result") or "")
    pending_reload = _truthy(telemetry.get("pending_reload"))

    bridge_age = now - int(bridge_hb.get("ts") or 0) if bridge_hb else None
    seq_age = now - int(seq_hb.get("ts") or 0) if seq_hb else None
    running_bridge = str(bridge_hb.get("version") or "") if bridge_hb else ""
    running_seq = str(seq_hb.get("version") or "") if seq_hb else ""

    bridge_state = _component_state(desired_bridge, installed_bridge, running_bridge, bridge_age)
    seq_state = _component_state(desired_seq, installed_seq, running_seq, seq_age)

    restart_safe = _truthy(seq_d.get("restart_safe"))
    open_positions = int(seq_d.get("open_positions") or bridge_d.get("sequence_open_positions") or 0)
    if pending_reload:
        if restart_safe and seq_age is not None and seq_age <= 45:
            restart_manager = "SAFE_RELOAD_ARMED"
        elif seq_hb:
            restart_manager = "WAITING_FOR_SAFE_STATE"
        else:
            restart_manager = "FIRST_RELOAD_REQUIRED"
    else:
        restart_manager = "NOT_NEEDED"

    return {
        "stable_release": release,
        "updater_version": updater_version,
        "update_result": update_result,
        "pending_reload": pending_reload,
        "restart_manager": restart_manager,
        "restart_safe": restart_safe,
        "sequence_open_positions": open_positions,
        "components": {
            "data_bridge": {
                "desired": desired_bridge,
                "installed": installed_bridge,
                "running": running_bridge,
                "status": bridge_state,
                "heartbeat_age_seconds": bridge_age,
            },
            "sequence_ea": {
                "desired": desired_seq,
                "installed": installed_seq,
                "running": running_seq,
                "status": seq_state,
                "heartbeat_age_seconds": seq_age,
            },
        },
    }


def system_status() -> dict:
    now = int(datetime.now(timezone.utc).timestamp())
    s = latest_snapshot()
    hbs = latest_heartbeats(20)
    comp = component_status()
    alerts = []
    if not s:
        alerts.append({"level": "RED", "code": "NO_SNAPSHOT", "message": "No market snapshot received."})
    elif now - s.sent_at > SETTINGS.max_snapshot_age_seconds:
        alerts.append({"level": "RED", "code": "SNAPSHOT_STALE", "message": "Market snapshot is stale."})
    if s and s.spread_points > SETTINGS.max_spread_points:
        alerts.append({"level": "AMBER", "code": "SPREAD_HIGH", "message": "Spread is above the configured demo guard."})

    for name, item in comp["components"].items():
        state = item["status"]
        label = "DataBridge" if name == "data_bridge" else "Sequence EA"
        if state == "OFFLINE":
            alerts.append({"level": "RED", "code": f"{name.upper()}_OFFLINE", "message": f"{label} heartbeat is offline/stale."})
        elif state == "UPDATE_PENDING":
            alerts.append({"level": "AMBER", "code": f"{name.upper()}_UPDATE_PENDING", "message": f"{label} update has not finished installing."})
        elif state == "RESTART_REQUIRED":
            alerts.append({"level": "AMBER", "code": f"{name.upper()}_RESTART_REQUIRED", "message": f"{label} is installed on disk but the running MT5 copy is older."})

    if comp["pending_reload"]:
        alerts.append(
            {
                "level": "AMBER",
                "code": "MT5_RELOAD_PENDING",
                "message": f"Runtime reload pending: {comp['restart_manager']}.",
            }
        )

    try:
        ml = ml_status()
    except Exception as exc:
        ml = {"enabled": SETTINGS.ml_data_enabled, "mode": "ERROR", "error": f"{type(exc).__name__}:{exc}"}
        alerts.append({"level": "AMBER", "code": "ML_DATA_FOUNDATION_ERROR", "message": "ML data collector status could not be read."})

    return {
        "cloud_version": SETTINGS.app_version,
        "paper_only": SETTINGS.paper_only,
        "snapshot_age_seconds": (now - s.sent_at) if s else None,
        "spread_points": s.spread_points if s else None,
        "heartbeats": hbs,
        "components": comp,
        "ml": ml,
        "alerts": alerts,
        "healthy": not any(a["level"] == "RED" for a in alerts),
    }


def export_csv_text() -> str:
    rows = build_trades()
    cols = [
        "trade_id",
        "analysis_id",
        "zone_id",
        "setup",
        "direction",
        "grade",
        "status",
        "entry_ts",
        "exit_ts",
        "entry_price",
        "exit_price",
        "pnl",
        "mfe_r",
        "mae_r",
        "bridge_version",
        "sequence_version",
        "cloud_version",
        "last_event",
    ]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        w.writerow(row)
    return out.getvalue()
