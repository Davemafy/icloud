from __future__ import annotations

"""Read-only DEMO/PAPER journal aggregation for the dashboard."""

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from .config import SETTINGS
from .db import recent_feedback, latest_heartbeats, latest_snapshot


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
        key = str(d.get("trade_id") or "|".join([str(row.get("analysis_id") or "NO_ANALYSIS"), str(row.get("zone_id") or "NO_ZONE"), str(d.get("setup") or "NO_SETUP")]))
        g = groups.setdefault(key, {
            "trade_id": key,
            "analysis_id": row.get("analysis_id") or "",
            "zone_id": row.get("zone_id") or "",
            "setup": d.get("setup") or "",
            "direction": d.get("direction") or "",
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
        })
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


def performance_summary() -> dict:
    trades = build_trades()
    closed = [x for x in trades if x.get("status") == "CLOSED"]
    wins = [x for x in closed if float(x.get("pnl") or 0.0) > 0]
    return {
        "paper_only": SETTINGS.paper_only,
        "trade_count": len(trades),
        "closed_trades": len(closed),
        "wins": len(wins),
        "win_rate": (len(wins) / len(closed) * 100.0) if closed else 0.0,
        "net_demo_pnl": sum(float(x.get("pnl") or 0.0) for x in closed),
    }


def system_status() -> dict:
    now = int(datetime.now(timezone.utc).timestamp())
    s = latest_snapshot()
    hbs = latest_heartbeats(20)
    alerts = []
    if not s:
        alerts.append({"level": "RED", "code": "NO_SNAPSHOT", "message": "No market snapshot received."})
    elif now - s.sent_at > SETTINGS.max_snapshot_age_seconds:
        alerts.append({"level": "RED", "code": "SNAPSHOT_STALE", "message": "Market snapshot is stale."})
    if s and s.spread_points > SETTINGS.max_spread_points:
        alerts.append({"level": "AMBER", "code": "SPREAD_HIGH", "message": "Spread is above the configured demo guard."})
    return {
        "cloud_version": SETTINGS.app_version,
        "paper_only": SETTINGS.paper_only,
        "snapshot_age_seconds": (now - s.sent_at) if s else None,
        "spread_points": s.spread_points if s else None,
        "heartbeats": hbs,
        "alerts": alerts,
        "healthy": not any(a["level"] == "RED" for a in alerts),
    }


def export_csv_text() -> str:
    rows = build_trades()
    cols = ["trade_id", "analysis_id", "zone_id", "setup", "direction", "status", "entry_ts", "exit_ts", "entry_price", "exit_price", "pnl", "mfe_r", "mae_r", "bridge_version", "sequence_version", "cloud_version", "last_event"]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        w.writerow(row)
    return out.getvalue()
