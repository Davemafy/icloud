from __future__ import annotations

"""Live execution-ownership synchronization for DEMO/PAPER mode.

Persisted analyses are snapshots. Zone lifecycle/ownership is updated on every
fresh MT5 snapshot, so presentation and plan export must not keep using an older
``active_thesis`` block until the next full analysis pass. This module overlays
current lifecycle truth at read time, fails closed during an owner-release or
owner-map mismatch, and makes target-hit changes trigger a fresh analysis.

It does not create zones, acquire ownership, send orders, size risk, or bypass
any existing M1/AI/safety gate.
"""

from datetime import datetime, timezone
from typing import Any, Callable

from .config import SETTINGS

_INSTALLED = False
_ORIGINAL_LATEST_ANALYSIS: Callable[..., Any] | None = None
_ORIGINAL_ACTIVE_PLAN_TEXT: Callable[..., str] | None = None
_ORIGINAL_ZONE_RENDER_TEXT: Callable[..., str] | None = None
_ORIGINAL_DASHBOARD_HTML: Callable[[str], str] | None = None


def _find_owner_zone(analysis: Any, owner: dict[str, Any]) -> Any | None:
    zones = list(getattr(analysis, "zones", []) or [])
    latest_id = str(owner.get("latest_zone_id") or "")
    if latest_id:
        exact = next((z for z in zones if str(getattr(z, "zone_id", "")) == latest_id), None)
        if exact is not None:
            return exact

    direction = str(owner.get("direction") or "")
    source_tf = str(owner.get("source_tf") or "")
    source_ts = int(owner.get("source_ts") or 0)
    for zone in zones:
        zdir = getattr(getattr(zone, "original_direction", None), "value", getattr(zone, "original_direction", ""))
        if str(zdir) != direction:
            continue
        if source_tf and str(getattr(zone, "source_tf", "")) != source_tf:
            continue
        if source_ts and int(getattr(zone, "source_ts", 0) or 0) != source_ts:
            continue
        return zone
    return None


def sync_analysis_live_ownership(analysis: Any, now: int | None = None) -> Any:
    """Overlay current persisted ownership on a freshly loaded Analysis object."""
    if analysis is None or not SETTINGS.paper_only:
        return analysis

    from .thesis_ownership_policy import (
        THESIS_OWNERSHIP_CONTRACT,
        _owner_meta,
        active_owner_snapshot,
    )

    if now is None:
        now = int(datetime.now(timezone.utc).timestamp())

    policy = dict(getattr(analysis, "execution_policy", {}) or {})
    previous = dict(policy.get("active_thesis") or {})
    previous_locked = bool(previous.get("locked"))
    owner = active_owner_snapshot(int(now))

    if owner is None:
        release_pending = previous_locked
        policy["active_thesis"] = {
            "contract": THESIS_OWNERSHIP_CONTRACT,
            "locked": False,
            "reason": (
                "LIVE_OWNER_RELEASED_PENDING_REANALYSIS"
                if release_pending
                else "NO_ACQUIRED_NONTERMINAL_THESIS"
            ),
            "interaction_alone_never_locks": True,
            "live_sync": True,
        }
        policy["live_thesis_sync"] = {
            "state": "RELEASE_PENDING_REANALYSIS" if release_pending else "NO_OWNER",
            "release_pending_reanalysis": release_pending,
            "source": "zone_reactions_live",
        }
        analysis.execution_policy = policy
        return analysis

    owner_zone = _find_owner_zone(analysis, owner)
    meta = _owner_meta(owner, owner_zone)
    meta.update(
        {
            "target1_hit_at": int(owner.get("target1_hit_at") or 0),
            "target2_hit_at": int(owner.get("target2_hit_at") or 0),
            "target3_hit_at": int(owner.get("target3_hit_at") or 0),
            "objective_complete_at": int(owner.get("objective_complete_at") or 0),
            "last_reason": str(owner.get("last_reason") or ""),
            "live_sync": True,
        }
    )
    policy["active_thesis"] = meta
    policy["live_thesis_sync"] = {
        "state": "OWNER_LIVE" if owner_zone is not None else "OWNER_OFF_CURRENT_MAP",
        "release_pending_reanalysis": False,
        "source": "zone_reactions_live",
        "reaction_key": str(owner.get("reaction_key") or ""),
    }
    analysis.execution_policy = policy
    return analysis


def _append_guard_reason(text: str, reason: str) -> str:
    lines = str(text or "").splitlines()
    out: list[str] = []
    found_mode = found_authority = found_reason = False
    for line in lines:
        if line.startswith("ea_mode="):
            out.append("ea_mode=WATCH_ONLY")
            found_mode = True
        elif line.startswith("execution_authority="):
            out.append("execution_authority=NONE")
            found_authority = True
        elif line.startswith("core_handoff_ready="):
            out.append("core_handoff_ready=0")
        elif line.startswith("liquidity_handoff_ready="):
            out.append("liquidity_handoff_ready=0")
        elif line.startswith("execution_guard_reason="):
            existing = line.split("=", 1)[1].strip()
            reasons = [x for x in existing.split(",") if x]
            if reason not in reasons:
                reasons.append(reason)
            out.append("execution_guard_reason=" + ",".join(reasons))
            found_reason = True
        else:
            out.append(line)
    if not found_mode:
        out.append("ea_mode=WATCH_ONLY")
    if not found_authority:
        out.append("execution_authority=NONE")
    if not found_reason:
        out.append("execution_guard_reason=" + reason)
    return "\n".join(out) + "\n"


def _plan_block_reason(analysis: Any) -> str:
    policy = dict(getattr(analysis, "execution_policy", {}) or {})
    sync = dict(policy.get("live_thesis_sync") or {})
    thesis = dict(policy.get("active_thesis") or {})

    if bool(sync.get("release_pending_reanalysis")):
        return "LIVE_THESIS_RELEASE_REANALYSIS_REQUIRED"

    if bool(thesis.get("locked")):
        if not bool(thesis.get("owner_zone_present", False)):
            return "LIVE_THESIS_OWNER_OFF_MAP"
        owner_id = str(thesis.get("owner_zone_id") or "")
        selected_id = str(getattr(analysis, "selected_zone_id", "") or "")
        if owner_id and selected_id != owner_id:
            return "LIVE_THESIS_OWNER_SELECTION_MISMATCH"
    return ""


def _zone_render_sync(text: str) -> str:
    """Never call an unlocked plan selection execution authority on the chart."""
    raw = str(text or "")
    locked = "active_thesis_locked=1\n" in raw
    if locked:
        return raw
    lines = []
    for line in raw.splitlines():
        if line.startswith("zone") and "_execution_authority=" in line:
            key = line.split("=", 1)[0]
            lines.append(key + "=0")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def _dashboard_wording(html: str) -> str:
    cleaned = str(html)
    cleaned = cleaned.replace("SELECTED • UNLOCKED", "PLAN SELECTED • NO EXECUTION AUTHORITY")
    cleaned = cleaned.replace("SELECTED / UNLOCKED", "PLAN SELECTED / NO EXECUTION AUTHORITY")
    cleaned = cleaned.replace(
        "is the current execution selection, subject to all normal M1 and safety gates.",
        "is the current plan selection only; execution still requires a qualifying M1 handoff and all safety gates.",
    )
    return cleaned


def install_live_ownership_sync() -> None:
    global _INSTALLED
    global _ORIGINAL_LATEST_ANALYSIS, _ORIGINAL_ACTIVE_PLAN_TEXT
    global _ORIGINAL_ZONE_RENDER_TEXT, _ORIGINAL_DASHBOARD_HTML

    if _INSTALLED:
        return

    from . import dashboard_view, db, engine, mt5_zone_render, scheduler
    from .thesis_ownership_policy import active_owner_snapshot

    _ORIGINAL_LATEST_ANALYSIS = db.latest_analysis

    def latest_analysis_live(ai_required: bool = False):
        analysis = _ORIGINAL_LATEST_ANALYSIS(ai_required=ai_required)
        if analysis is None or not SETTINGS.paper_only:
            return analysis
        snap = db.latest_snapshot()
        now = int(snap.sent_at) if snap is not None else int(datetime.now(timezone.utc).timestamp())
        return sync_analysis_live_ownership(analysis, now)

    db.latest_analysis = latest_analysis_live
    # scheduler imported latest_analysis before this assignment because this
    # installer imports scheduler explicitly. Keep its module binding aligned.
    scheduler.latest_analysis = latest_analysis_live

    def thesis_signature_live(now_utc: int) -> str:
        owner = active_owner_snapshot(now_utc)
        if owner is None:
            return ""
        hits = "".join(
            "1" if int(owner.get(key) or 0) else "0"
            for key in ("target1_hit_at", "target2_hit_at", "target3_hit_at")
        )
        return f"{owner.get('reaction_key','')}|{owner.get('status','')}|hits={hits}"

    scheduler._thesis_signature = thesis_signature_live

    _ORIGINAL_ACTIVE_PLAN_TEXT = engine.active_plan_text

    def active_plan_text_live(analysis, snapshot=None):
        synced = sync_analysis_live_ownership(
            analysis,
            int(snapshot.sent_at) if snapshot is not None else None,
        )
        text = _ORIGINAL_ACTIVE_PLAN_TEXT(synced, snapshot)
        reason = _plan_block_reason(synced)
        return _append_guard_reason(text, reason) if reason else text

    active_plan_text_live._tradezone_live_ownership_sync_v6524 = True
    engine.active_plan_text = active_plan_text_live

    _ORIGINAL_ZONE_RENDER_TEXT = mt5_zone_render.mt5_zone_render_text

    def mt5_zone_render_text_live(analysis):
        synced = sync_analysis_live_ownership(analysis)
        return _zone_render_sync(_ORIGINAL_ZONE_RENDER_TEXT(synced))

    mt5_zone_render.mt5_zone_render_text = mt5_zone_render_text_live

    _ORIGINAL_DASHBOARD_HTML = dashboard_view.compact_dashboard_html

    def compact_dashboard_html_live(html: str) -> str:
        return _dashboard_wording(_ORIGINAL_DASHBOARD_HTML(html))

    dashboard_view.compact_dashboard_html = compact_dashboard_html_live
    _INSTALLED = True
