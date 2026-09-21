from __future__ import annotations

"""Clinical-review observability hardening.

This module is deliberately restricted to journal aggregation, component-status
semantics, and human dashboard presentation. It does not alter /mt5/plan, zone
qualification, AI approval, risk sizing, order placement, or Sequence EA logic.
"""

import csv
import io
from datetime import datetime, timezone
from typing import Callable

from .config import SETTINGS

_INSTALLED = False

# Only real position/deal lifecycle events belong in Trade History / performance.
# ML_CANDIDATE is shadow research telemetry and must never be counted as a trade.
_TRADE_EVENTS = {
    "ENTRY_OPENED",
    "POSITION_MARK",
    "POSITION_EXIT",
    "TP_HIT",
    "SL_HIT",
    "TRADE_CLOSED",
}

_AUDIT_CARD = (
    '<div class="card" style="margin-top:12px">'
    '<h3>Selected-zone audit <span class="pill paper">READ ONLY</span></h3>'
    '<div id="selectedZoneAudit" class="note">Waiting for selected-zone audit data…</div>'
    '<p class="note"><b>Version domains:</b> Cloud application versions and MT5 stable-package '
    'releases are separate namespaces. Different numbers do not indicate a version mismatch.</p>'
    '</div>'
)

_AUDIT_SCRIPT = r'''
<script id="clinical-review-readonly-script">
(function(){
  function journalState(){
    try{return (typeof currentJournal!=='undefined' && currentJournal)?currentJournal:null;}catch(e){return null;}
  }
  function fmtAge(ts){
    if(!ts)return '—';
    const sec=Math.max(0,Math.floor(Date.now()/1000-Number(ts)));
    if(sec<60)return sec+'s ago';
    if(sec<3600)return Math.floor(sec/60)+'m ago';
    return (sec/3600).toFixed(1)+'h ago';
  }
  function refreshAudit(){
    const out=document.getElementById('selectedZoneAudit');
    if(!out)return;
    const j=journalState(),z=j?.zone||{};
    if(!z.zone_id){
      out.textContent='No execution zone is currently selected. The HTF map may still contain valid published zones.';
      return;
    }
    const conf=Array.isArray(z.confluences)?z.confluences:[];
    let dxy='Neutral';
    if(z.dxy_support==='SUPPORT')dxy='Supports '+(z.direction||'selected')+' thesis';
    else if(z.dxy_support==='CONFLICT')dxy='Conflicts with '+(z.direction||'selected')+' thesis';
    const bits=[
      'Zone '+z.zone_id+' ('+(z.source_tf||'—')+').',
      'Confluences '+conf.length+': '+(conf.length?conf.join(', '):'none reported')+'.',
      'DXY relationship: '+dxy+'.',
      'Last requalified: '+fmtAge(j?.generated_at)+'.',
      'Trade History counts only ENTRY/position/exit lifecycle events; ML_CANDIDATE remains research telemetry and is not a trade.'
    ];
    out.textContent=bits.join(' ');
  }
  refreshAudit();
  window.setInterval(refreshAudit,3000);
})();
</script>
'''.strip()


def _build_trades_factory(journal) -> Callable[[int], list[dict]]:
    def build_trades(limit_events: int = 5000) -> list[dict]:
        rows = list(reversed(journal.recent_feedback(limit_events)))
        groups: dict[str, dict] = {}
        seen_event_ids: set[str] = set()

        for row in rows:
            event = str(row.get("event") or "").upper()
            if event not in _TRADE_EVENTS:
                continue

            d = journal.parse_details(row.get("details"))
            setup = journal._canonical_setup(d)
            position_id = d.get("position_id")
            raw_trade_id = str(d.get("trade_id") or "")
            event_uid = str(d.get("event_uid") or "").strip()
            if not event_uid:
                deal_id = d.get("deal_id")
                if deal_id not in (None, "", 0, "0"):
                    event_uid = f"{event}|DEAL|{deal_id}"
                elif event == "TRADE_CLOSED" and position_id not in (None, "", 0, "0"):
                    event_uid = f"{event}|POSITION|{position_id}"
            if event_uid:
                if event_uid in seen_event_ids:
                    continue
                seen_event_ids.add(event_uid)

            key = (
                f"POSITION:{position_id}"
                if position_id not in (None, "", 0, "0")
                else raw_trade_id
                or "|".join(
                    [
                        str(row.get("analysis_id") or "NO_ANALYSIS"),
                        str(row.get("zone_id") or "NO_ZONE"),
                        setup or "EXECUTION",
                    ]
                )
            )
            display_id = (
                f"{setup or 'TRADE'} · POS {position_id}"
                if position_id not in (None, "", 0, "0")
                else (setup or "TRADE")
            )

            g = groups.setdefault(
                key,
                {
                    "trade_id": raw_trade_id or key,
                    "campaign_id": raw_trade_id,
                    "display_id": display_id,
                    "position_id": position_id,
                    "analysis_id": row.get("analysis_id") or "",
                    "zone_id": row.get("zone_id") or "",
                    "setup": setup,
                    "direction": d.get("direction") or "",
                    "grade": d.get("grade") or "",
                    "status": "OPEN" if event == "POSITION_MARK" else "PLANNED",
                    "entry_ts": None,
                    "exit_ts": None,
                    "entry_price": None,
                    "exit_price": None,
                    "volume": d.get("volume"),
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

            ts = int(row.get("ts") or 0)
            price = float(row.get("price") or 0.0)
            g["event_count"] += 1
            g["last_event"] = event
            g["last_ts"] = ts
            if setup:
                g["setup"] = setup
            if raw_trade_id and not g.get("campaign_id"):
                g["campaign_id"] = raw_trade_id
            if raw_trade_id and str(g.get("trade_id") or "").startswith("POSITION:"):
                g["trade_id"] = raw_trade_id
            if d.get("direction"):
                g["direction"] = d["direction"]
            if d.get("grade"):
                g["grade"] = d["grade"]
            if d.get("bridge_version"):
                g["bridge_version"] = d["bridge_version"]
            if d.get("sequence_version"):
                g["sequence_version"] = d["sequence_version"]
            if d.get("volume") is not None:
                g["volume"] = d.get("volume")
            if position_id not in (None, "", 0, "0"):
                g["position_id"] = position_id
                g["display_id"] = f"{g.get('setup') or 'TRADE'} · POS {position_id}"
            elif setup:
                g["display_id"] = setup

            if event == "ENTRY_OPENED":
                g["status"] = "OPEN"
                g["entry_ts"] = g["entry_ts"] or ts
                g["entry_price"] = g["entry_price"] or price
            elif event == "POSITION_MARK":
                if g["status"] not in {"CLOSED", "MANAGING"}:
                    g["status"] = "OPEN"
                if g["entry_price"] is None and d.get("entry_price") is not None:
                    g["entry_price"] = float(d.get("entry_price") or 0.0) or None
                if g["entry_ts"] is None:
                    g["entry_ts"] = ts
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

    return build_trades


def _performance_summary_factory(journal) -> Callable[[], dict]:
    def performance_summary() -> dict:
        trades = journal.build_trades()
        closed = [x for x in trades if x.get("status") == "CLOSED"]
        open_trades = [x for x in trades if x.get("status") in {"OPEN", "MANAGING"}]
        wins = [x for x in closed if float(x.get("pnl") or 0.0) > 0]
        now = int(datetime.now(timezone.utc).timestamp())
        last_7d = [x for x in closed if int(x.get("exit_ts") or 0) >= now - 7 * 86400]
        observations = [
            x for x in journal.recent_feedback(5000)
            if str(x.get("event") or "").upper() == "ML_CANDIDATE"
        ]
        unique_observations: set[str] = set()
        for row in observations:
            d = journal.parse_details(row.get("details"))
            candidate_id = str(d.get("candidate_id") or "")
            if candidate_id:
                unique_observations.add(candidate_id)

        return {
            "paper_only": SETTINGS.paper_only,
            "trade_count": len(trades),
            "open_trades": len(open_trades),
            "closed_trades": len(closed),
            "wins": len(wins),
            "win_rate": (len(wins) / len(closed) * 100.0) if closed else None,
            "net_demo_pnl": sum(float(x.get("pnl") or 0.0) for x in closed),
            "research_observations": len(observations),
            "unique_research_observations": len(unique_observations),
            "last_7d": {
                "closed_trades": len(last_7d),
                "net_demo_pnl": sum(float(x.get("pnl") or 0.0) for x in last_7d),
            },
            "by_setup": journal._bucket_summary(closed, "setup"),
            "by_direction": journal._bucket_summary(closed, "direction"),
            "by_grade": journal._bucket_summary(closed, "grade"),
        }

    return performance_summary


def _export_csv_factory(journal) -> Callable[[], str]:
    def export_csv_text() -> str:
        rows = journal.build_trades()
        cols = [
            "trade_id",
            "campaign_id",
            "display_id",
            "position_id",
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
            "volume",
            "pnl",
            "mfe_r",
            "mae_r",
            "bridge_version",
            "sequence_version",
            "cloud_version",
            "last_event",
        ]
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return out.getvalue()

    return export_csv_text


def _component_status_factory(original: Callable[[], dict]) -> Callable[[], dict]:
    def component_status() -> dict:
        status = original()
        components = status.get("components", {})
        all_current = bool(components) and all(
            str(item.get("status") or "") == "CURRENT" for item in components.values()
        )
        pending = bool(status.get("pending_reload"))
        result = str(status.get("update_result") or "")
        status["release_scope"] = "MT5_STABLE_PACKAGE"
        status["update_state"] = (
            "RELOAD_PENDING" if pending else "CURRENT" if all_current else "ATTENTION"
        )
        status["update_result_historical"] = bool(result and not pending and all_current)
        status["update_result_explanation"] = (
            "Last installer outcome only; current installed/running component truth is authoritative."
            if status["update_result_historical"]
            else "Current updater/reload state."
        )
        return status

    return component_status


def _system_status_factory(original: Callable[[], dict]) -> Callable[[], dict]:
    def system_status() -> dict:
        status = original()
        age = status.get("snapshot_age_seconds")
        status["snapshot_source_age_seconds"] = age
        status["snapshot_age_basis"] = "MT5_SOURCE_TIMESTAMP_VS_CLOUD_UTC"
        status["snapshot_clock_note"] = (
            "VPS/MT5 taskbar clock may use a different timezone; compare epoch/source age, not wall-clock labels."
        )
        if isinstance(age, (int, float)) and age < -60:
            alerts = list(status.get("alerts") or [])
            alerts.append(
                {
                    "level": "AMBER",
                    "code": "SNAPSHOT_CLOCK_SKEW",
                    "message": (
                        "MT5 snapshot source timestamp is materially ahead of cloud UTC; "
                        "verify MT5/server clock basis."
                    ),
                }
            )
            status["alerts"] = alerts
        status["healthy"] = not any(
            item.get("level") == "RED" for item in status.get("alerts", [])
        )
        return status

    return system_status


def _dashboard_factory(original: Callable[[str], str]) -> Callable[[str], str]:
    def compact_dashboard_html(html: str) -> str:
        cleaned = original(html)
        cleaned = cleaned.replace("<h3>Stable release</h3>", "<h3>MT5 stable package</h3>")
        cleaned = cleaned.replace("auto-updates every 3s", "dashboard refreshes every 3s")
        cleaned = cleaned.replace("<h3>Recorded trades</h3>", "<h3>Executed trades</h3>")
        cleaned = cleaned.replace("<th>Distance H1 ATR</th>", "<th>Distance (× H1 ATR)</th>")
        cleaned = cleaned.replace(
            "Updater <b>${esc(c.updater_version||'—')}</b> • result <b>${esc(c.update_result||'—')}</b> • reload <b>${c.pending_reload?'YES':'NO'}</b>",
            "Updater <b>${esc(c.updater_version||'—')}</b> • last installer result <b>${esc(c.update_result||'—')}</b> • current reload <b>${c.pending_reload?'PENDING':'NONE'}</b>",
        )
        cleaned = cleaned.replace("Snapshot age <b>", "MT5 source age <b>")
        cleaned = cleaned.replace("${esc(x.trade_id)}", "${esc(x.display_id||x.trade_id)}")
        cleaned = cleaned.replace(
            "$('winRate').textContent=num(d.win_rate,1)+'%'",
            "$('winRate').textContent=(d.closed_trades??0)>0?(num(d.win_rate,1)+'%'):'—'",
        )

        journal_anchor = '<h2>Live trading journal'
        if 'id="selectedZoneAudit"' not in cleaned and journal_anchor in cleaned:
            cleaned = cleaned.replace(journal_anchor, _AUDIT_CARD + "\n" + journal_anchor, 1)
        if 'id="clinical-review-readonly-script"' not in cleaned and "</body>" in cleaned:
            cleaned = cleaned.replace("</body>", _AUDIT_SCRIPT + "\n</body>", 1)
        return cleaned

    return compact_dashboard_html


def install_clinical_review_hardening() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import dashboard_view
    from . import journal

    original_component_status = journal.component_status
    original_system_status = journal.system_status
    original_dashboard = dashboard_view.compact_dashboard_html

    journal.build_trades = _build_trades_factory(journal)
    journal.performance_summary = _performance_summary_factory(journal)
    journal.export_csv_text = _export_csv_factory(journal)
    journal.component_status = _component_status_factory(original_component_status)
    journal.system_status = _system_status_factory(original_system_status)
    dashboard_view.compact_dashboard_html = _dashboard_factory(original_dashboard)

    _INSTALLED = True
