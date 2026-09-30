from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from .config import SETTINGS
from .db import audit, latest_analysis, latest_snapshot
from .institutional_two_zone import primary_zone_approaching, primary_zone_interacting
from .engine import atr
from .liquidity_reversal_handoff import detect_liquidity_reversal_handoff
from .prompt_contract import prompt_snapshot_complete
from .runtime_version_truth import install_runtime_version_truth_policy
from .thesis_hard_release import hard_release_stale_thesis
from .thesis_ownership_policy import (
    active_owner_snapshot,
    owner_core_interacting,
    owner_m1_handoff_interacting,
)
from .timezones import safe_zoneinfo
from .zone_reaction_lifecycle import publication_state_for_zone

install_runtime_version_truth_policy()

_last_keys: set[str] = set()
_zone_interaction_latch: set[str] = set()
_thesis_m1_handoff_latch: set[str] = set()
_last_snapshot_seen: int = 0
_thesis_state_latch: str = ""
_liquidity_reversal_latch: str = ""
_wrong_side_context_latch: set[str] = set()
_market_drift_latch: str = ""


def _parse_hhmm(value: str, fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        hh, mm = value.strip().split(":", 1)
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except Exception:
        pass
    return fallback


def _times() -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for x in SETTINGS.session_analysis_times.split(","):
        try:
            hh, mm = x.strip().split(":", 1)
            h, m = int(hh), int(mm)
            if 0 <= h <= 23 and 0 <= m <= 59:
                out.append((h, m))
        except Exception:
            continue
    return out


def _trading_weekdays() -> set[int]:
    out: set[int] = set()
    for raw in SETTINGS.trading_day_weekdays.split(","):
        try:
            x = int(raw.strip())
            if 0 <= x <= 6:
                out.add(x)
        except Exception:
            continue
    return out or {0, 1, 2, 3}


def scheduler_status() -> dict:
    tz = safe_zoneinfo(SETTINGS.timezone_name)
    now = datetime.now(tz)
    day_open = _parse_hhmm(SETTINGS.trading_day_open_time, (23, 6))
    week_open = _parse_hhmm(SETTINGS.week_open_time, (23, 11))
    return {
        "timezone": SETTINGS.timezone_name,
        "timezone_resolved": str(tz),
        "local_time": now.isoformat(),
        "analysis_times": [f"{h:02d}:{m:02d}" for h, m in _times()],
        "trading_day_open_time": f"{day_open[0]:02d}:{day_open[1]:02d}",
        "trading_day_weekdays": sorted(_trading_weekdays()),
        "week_open_weekday": max(0, min(6, SETTINGS.week_open_weekday)),
        "week_open_time": f"{week_open[0]:02d}:{week_open[1]:02d}",
        "poll_seconds": SETTINGS.scheduler_poll_seconds,
        "snapshot_primary_zone_refresh": bool(SETTINGS.paper_only),
        "primary_zone_latch_count": len(_zone_interaction_latch),
        "thesis_m1_handoff_latch_count": len(_thesis_m1_handoff_latch),
        "thesis_state_latch": _thesis_state_latch or None,
        "liquidity_reversal_latch": _liquidity_reversal_latch or None,
        "wrong_side_context_latch_count": len(_wrong_side_context_latch),
        "market_drift_latch": _market_drift_latch or None,
        "market_drift_reanalysis_h1_atr": float(getattr(SETTINGS, "market_drift_reanalysis_h1_atr", 2.0)),
        "market_drift_reanalysis_min_age_minutes": int(getattr(SETTINGS, "market_drift_reanalysis_min_age_minutes", 10)),
        "market_drift_structural_cadence": "NEW_CLOSED_H1_ONLY",
        "last_snapshot_seen": _last_snapshot_seen or None,
    }


def _due_reasons(now_local: datetime) -> list[str]:
    reasons: list[str] = []
    week_day = max(0, min(6, SETTINGS.week_open_weekday))
    week_h, week_m = _parse_hhmm(SETTINGS.week_open_time, (23, 11))
    day_h, day_m = _parse_hhmm(SETTINGS.trading_day_open_time, (23, 6))
    trading_days = _trading_weekdays()

    is_week_open = now_local.weekday() == week_day and now_local.hour == week_h and now_local.minute == week_m
    if is_week_open:
        reasons.append("WEEK_OPEN")
    is_day_open = now_local.weekday() in trading_days and now_local.hour == day_h and now_local.minute == day_m
    if is_day_open and not (is_week_open and week_h == day_h and week_m == day_m):
        reasons.append("TRADING_DAY_OPEN")
    for h, m in _times():
        if now_local.hour == h and now_local.minute == m:
            reasons.append(f"SESSION_{h:02d}{m:02d}")

    snap = latest_snapshot()
    if snap:
        now_utc = int(now_local.astimezone(timezone.utc).timestamp())
        for n in snap.news:
            if n.currency.upper() != "USD" or n.impact.upper() != "HIGH":
                continue
            for off, tag in [(-10, "PRE_NEWS"), (10, "POST_NEWS")]:
                target = n.ts + off * 60
                if abs(now_utc - target) <= 30:
                    reasons.append(f"{tag}:{n.title or 'USD_HIGH'}")
    return reasons


def _fresh_complete_snapshot(snap, now_utc: int) -> bool:
    if snap is None:
        return False
    complete = getattr(snap, "complete", None)
    if callable(complete):
        try:
            if not bool(complete()):
                return False
        except Exception:
            return False
    try:
        if not prompt_snapshot_complete(snap):
            return False
    except AttributeError:
        # Lightweight test doubles / compatibility callers may only expose
        # complete(). Real MarketSnapshot objects always take the strict prompt path.
        if not callable(complete):
            return False
    age = max(0, int(now_utc) - int(snap.sent_at))
    return age <= SETTINGS.max_snapshot_age_seconds


def _interaction_ids(snap) -> set[str]:
    """Return edge-sensitive approach/contact tokens for scheduler refresh.

    A zone can spend many snapshots inside the broad M15-ATR approach buffer
    before the executable quote actually overlaps its tactical core. Using only
    zone_id for both states latched the approach event and hid the later core
    contact, so run_analysis() never got the transition that promotes M1_READY.
    Keep approach refreshes, but make CORE a distinct edge.
    """
    if not SETTINGS.paper_only:
        return set()
    a = latest_analysis(ai_required=False)
    if a is None:
        return set()

    ids: set[str] = set()
    for z in a.zones:
        publication = publication_state_for_zone(z)
        live_touch = int(publication.get("live_core_touched_at") or 0) if publication else 0
        if live_touch:
            # Persisted post-publication contact is authoritative even if the
            # quote has already left the core before the scheduler observes it.
            # Including the timestamp makes this a one-shot contact edge.
            ids.add(f"CONTACT:{z.zone_id}:{live_touch}")

        if primary_zone_interacting(z, snap):
            ids.add(f"CORE:{z.zone_id}")
        elif primary_zone_approaching(z, snap):
            ids.add(f"APPROACH:{z.zone_id}")

    owner = owner_core_interacting(snap)
    if owner is not None:
        owner_id = str(owner.get("latest_zone_id") or owner.get("reaction_key") or "")
        if owner_id:
            ids.add(f"THESIS:{owner_id}")
    return ids


def _wrong_side_context_ids(snap) -> set[str]:
    """Detect stale non-owner/non-selected map zones that live price has passed.

    A fresh analysis must remove these from today's alert map. Selected/owned
    geometry is excluded here because it may still be required locally for M15
    accepted-invalidation and flip monitoring.
    """
    if not SETTINGS.paper_only:
        return set()
    a = latest_analysis(ai_required=False)
    if a is None:
        return set()
    selected = str(getattr(a, "selected_zone_id", "") or "")
    owner = active_owner_snapshot(int(getattr(snap, "sent_at", 0) or 0))
    owner_id = str((owner or {}).get("ownership_zone_id") or (owner or {}).get("latest_zone_id") or "")
    try:
        mid = float(snap.mid)
    except (TypeError, ValueError):
        return set()

    out: set[str] = set()
    for z in list(getattr(a, "zones", []) or []):
        zid = str(getattr(z, "zone_id", "") or "")
        if not zid or zid == selected or (owner_id and zid == owner_id):
            continue
        direction = str(getattr(getattr(z, "original_direction", None), "value", getattr(z, "original_direction", ""))).upper()
        low = min(float(getattr(z, "zone_low", 0.0)), float(getattr(z, "zone_high", 0.0)))
        high = max(float(getattr(z, "zone_low", 0.0)), float(getattr(z, "zone_high", 0.0)))
        wrong = (direction == "BUY" and low > mid) or (direction == "SELL" and high < mid)
        if wrong:
            out.add(zid)
    return out


def _latest_closed_h1_ts(snap) -> int:
    """Latest causally closed H1 bar in the snapshot."""
    sent_at = int(getattr(snap, "sent_at", 0) or 0)
    closed = [
        int(getattr(bar, "ts", 0) or 0)
        for bar in list(getattr(snap, "xau_h1", []) or [])
        if int(getattr(bar, "ts", 0) or 0) > 0
        and int(getattr(bar, "ts", 0) or 0) + 3600 <= sent_at
    ]
    return max(closed, default=0)


def _market_drift_refresh(snap, now_utc: int) -> dict:
    """Detect when an unowned selected map has become tactically remote.

    This is a map-refresh trigger only. It never invalidates the existing zone,
    acquires thesis ownership, promotes M1 authority, or sends an order. A fresh
    analysis may keep the same zone if no better qualified battlefield exists.
    """
    if not bool(getattr(SETTINGS, "paper_only", False)):
        return {}
    analysis = latest_analysis(ai_required=False)
    if analysis is None:
        return {}
    if active_owner_snapshot(int(now_utc)) is not None:
        return {}

    selected_id = str(getattr(analysis, "selected_zone_id", "") or "")
    if not selected_id:
        return {}
    zone = next((z for z in list(getattr(analysis, "zones", []) or []) if str(getattr(z, "zone_id", "")) == selected_id), None)
    if zone is None:
        return {}

    readiness = str(getattr(zone, "core_method", "") or "").split("|", 1)[0].upper()
    if readiness not in {"ARMED", "WATCH"}:
        return {}

    generated_at = int(getattr(analysis, "generated_at", 0) or 0)
    min_age = max(1, int(getattr(SETTINGS, "market_drift_reanalysis_min_age_minutes", 10))) * 60
    if generated_at <= 0 or max(0, int(now_utc) - generated_at) < min_age:
        return {}

    try:
        mid = float(snap.mid)
        low = min(float(getattr(zone, "zone_low")), float(getattr(zone, "zone_high")))
        high = max(float(getattr(zone, "zone_low")), float(getattr(zone, "zone_high")))
    except (TypeError, ValueError, AttributeError):
        return {}

    direction = str(getattr(getattr(zone, "original_direction", None), "value", getattr(zone, "original_direction", ""))).upper()
    # Only refresh when price is still on the valid approach side and has moved
    # farther away in the original thesis direction. Wrong-side/invalidated
    # structures are handled by the dedicated lifecycle/flip logic.
    if direction == "SELL":
        if mid >= low:
            return {}
        distance = low - mid
    elif direction == "BUY":
        if mid <= high:
            return {}
        distance = mid - high
    else:
        return {}

    explicit_h1 = float(getattr(snap, "atr_h1", 0.0) or 0.0)
    h1_atr = explicit_h1 if explicit_h1 > 0.0 else float(atr(list(getattr(snap, "xau_h1", []) or [])) or 0.0)
    if h1_atr <= 0.0:
        return {}

    distance_atr = distance / h1_atr
    threshold = max(0.25, float(getattr(SETTINGS, "market_drift_reanalysis_h1_atr", 2.0)))
    if distance_atr < threshold:
        return {}

    # H4/H1 zoning cannot legitimately change on every tick. Once remote, rerun
    # the structural map at most once per newly closed H1 bar. M15/M1 execution
    # monitoring remains continuous and independent.
    closed_h1_ts = _latest_closed_h1_ts(snap)
    if closed_h1_ts <= 0:
        return {}

    return {
        "signature": f"{selected_id}|{direction}|H1:{closed_h1_ts}",
        "zone_id": selected_id,
        "direction": direction,
        "distance_h1_atr": round(distance_atr, 3),
        "analysis_age_seconds": max(0, int(now_utc) - generated_at),
        "threshold_h1_atr": threshold,
        "closed_h1_ts": closed_h1_ts,
        "cadence": "NEW_CLOSED_H1_ONLY",
    }


def _m1_handoff_ids(snap) -> set[str]:
    if not SETTINGS.paper_only:
        return set()
    owner = owner_m1_handoff_interacting(snap)
    if owner is None:
        return set()
    owner_id = str(owner.get("latest_zone_id") or owner.get("reaction_key") or "")
    return {f"THESIS_M1:{owner_id}"} if owner_id else set()


def _thesis_signature(now_utc: int) -> str:
    owner = active_owner_snapshot(now_utc)
    if owner is None:
        return ""
    return f"{owner.get('reaction_key','')}|{owner.get('status','')}"


def _liquidity_reversal_signature(snap) -> str:
    if not SETTINGS.paper_only:
        return ""
    a = latest_analysis(ai_required=False)
    if a is None:
        return ""
    handoff = detect_liquidity_reversal_handoff(a, snap)
    if not bool(handoff.get("active")):
        return ""
    return (
        f"{handoff.get('direction','')}|{handoff.get('context_zone_id','')}|"
        f"{handoff.get('liquidity_label','')}|{handoff.get('sweep_ts',0)}|"
        f"{handoff.get('displacement_ts',0)}"
    )


async def scheduler_loop(run_analysis: Callable[[str], Awaitable[object]]) -> None:
    global _last_snapshot_seen, _thesis_state_latch, _liquidity_reversal_latch, _wrong_side_context_latch, _market_drift_latch
    tz = safe_zoneinfo(SETTINGS.timezone_name)
    startup_analysis_pending = True
    while True:
        try:
            now = datetime.now(tz)
            ran_analysis = False
            for reason in _due_reasons(now):
                key = f"{now.date()}:{reason}"
                if key in _last_keys:
                    continue
                _last_keys.add(key)
                await run_analysis(reason)
                ran_analysis = True

            if startup_analysis_pending:
                if ran_analysis:
                    startup_analysis_pending = False
                else:
                    snap = latest_snapshot()
                    now_utc = int(now.astimezone(timezone.utc).timestamp())
                    if _fresh_complete_snapshot(snap, now_utc):
                        await run_analysis("SERVICE_STARTUP_FRESH_SNAPSHOT")
                        startup_analysis_pending = False
                        ran_analysis = True

            snap = latest_snapshot()
            now_utc = int(now.astimezone(timezone.utc).timestamp())
            if SETTINGS.paper_only and _fresh_complete_snapshot(snap, now_utc) and int(snap.sent_at) != _last_snapshot_seen:
                _last_snapshot_seen = int(snap.sent_at)

                # Release stale persisted ownership immediately when stored-zone M15
                # invalidation is unequivocal. Release itself grants no new trade.
                hard_released = hard_release_stale_thesis(snap)

                thesis_sig = _thesis_signature(now_utc)
                thesis_state_changed = thesis_sig != _thesis_state_latch
                previous_thesis_sig = _thesis_state_latch
                _thesis_state_latch = thesis_sig

                current_ids = _interaction_ids(snap)
                new_ids = current_ids - _zone_interaction_latch
                _zone_interaction_latch.clear()
                _zone_interaction_latch.update(current_ids)

                current_m1_ids = _m1_handoff_ids(snap)
                new_m1_ids = current_m1_ids - _thesis_m1_handoff_latch
                _thesis_m1_handoff_latch.clear()
                _thesis_m1_handoff_latch.update(current_m1_ids)

                lr_sig = _liquidity_reversal_signature(snap)
                lr_changed = bool(lr_sig and lr_sig != _liquidity_reversal_latch)
                _liquidity_reversal_latch = lr_sig

                wrong_side_ids = _wrong_side_context_ids(snap)
                new_wrong_side_ids = wrong_side_ids - _wrong_side_context_latch
                _wrong_side_context_latch.clear()
                _wrong_side_context_latch.update(wrong_side_ids)

                drift = _market_drift_refresh(snap, now_utc)
                drift_sig = str(drift.get("signature") or "")
                drift_changed = bool(drift_sig and drift_sig != _market_drift_latch)
                if not drift_sig:
                    _market_drift_latch = ""

                refresh_reason = ""
                if hard_released:
                    refresh_reason = "STALE_THESIS_HARD_RELEASE"
                elif thesis_state_changed and (thesis_sig or previous_thesis_sig):
                    refresh_reason = f"ACTIVE_THESIS_STATE:{thesis_sig or 'RELEASED'}"
                elif lr_changed:
                    refresh_reason = f"LIQUIDITY_REVERSAL_HANDOFF:{lr_sig}"
                elif new_wrong_side_ids:
                    refresh_reason = f"WRONG_SIDE_CONTEXT_REQUALIFY:{','.join(sorted(new_wrong_side_ids)[:2])}"
                elif new_m1_ids:
                    refresh_reason = f"ACTIVE_THESIS_M1_HANDOFF:{','.join(sorted(new_m1_ids)[:2])}"
                elif new_ids:
                    refresh_reason = f"PRIMARY_ZONE_REFRESH:{','.join(sorted(new_ids)[:2])}"
                elif drift_changed:
                    refresh_reason = (
                        f"MARKET_DRIFT_REANALYSIS:{drift.get('zone_id','')}:"
                        f"{float(drift.get('distance_h1_atr') or 0.0):.2f}H1ATR"
                    )

                if refresh_reason and not ran_analysis:
                    audit(now_utc, "scheduler.execution_refresh", f"snapshot={snap.sent_at} reason={refresh_reason}")
                    await run_analysis(refresh_reason)
                    ran_analysis = True

                if drift_sig and (drift_changed or ran_analysis):
                    _market_drift_latch = drift_sig

            if len(_last_keys) > 300:
                cutoff = (now.date() - timedelta(days=7)).isoformat()
                for k in list(_last_keys):
                    if k[:10] < cutoff:
                        _last_keys.discard(k)
        except Exception as exc:
            audit(int(datetime.now(timezone.utc).timestamp()), "scheduler.error", f"{type(exc).__name__}:{exc}")
        await asyncio.sleep(max(5, SETTINGS.scheduler_poll_seconds))