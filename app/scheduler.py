from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from .config import SETTINGS
from .db import audit, latest_analysis, latest_snapshot
from .institutional_two_zone import primary_zone_approaching
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

install_runtime_version_truth_policy()

_last_keys: set[str] = set()
_zone_interaction_latch: set[str] = set()
_thesis_m1_handoff_latch: set[str] = set()
_last_snapshot_seen: int = 0
_thesis_state_latch: str = ""
_liquidity_reversal_latch: str = ""


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
    if not SETTINGS.paper_only:
        return set()
    a = latest_analysis(ai_required=False)
    if a is None:
        return set()
    ids = {z.zone_id for z in a.zones if primary_zone_approaching(z, snap)}
    owner = owner_core_interacting(snap)
    if owner is not None:
        owner_id = str(owner.get("latest_zone_id") or owner.get("reaction_key") or "")
        if owner_id:
            ids.add(f"THESIS:{owner_id}")
    return ids


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
    global _last_snapshot_seen, _thesis_state_latch, _liquidity_reversal_latch
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

                refresh_reason = ""
                if hard_released:
                    refresh_reason = "STALE_THESIS_HARD_RELEASE"
                elif thesis_state_changed and (thesis_sig or previous_thesis_sig):
                    refresh_reason = f"ACTIVE_THESIS_STATE:{thesis_sig or 'RELEASED'}"
                elif lr_changed:
                    refresh_reason = f"LIQUIDITY_REVERSAL_HANDOFF:{lr_sig}"
                elif new_m1_ids:
                    refresh_reason = f"ACTIVE_THESIS_M1_HANDOFF:{','.join(sorted(new_m1_ids)[:2])}"
                elif new_ids:
                    refresh_reason = f"PRIMARY_ZONE_REFRESH:{','.join(sorted(new_ids)[:2])}"

                if refresh_reason and not ran_analysis:
                    audit(now_utc, "scheduler.execution_refresh", f"snapshot={snap.sent_at} reason={refresh_reason}")
                    await run_analysis(refresh_reason)
                    ran_analysis = True

            if len(_last_keys) > 300:
                cutoff = (now.date() - timedelta(days=7)).isoformat()
                for k in list(_last_keys):
                    if k[:10] < cutoff:
                        _last_keys.discard(k)
        except Exception as exc:
            audit(int(datetime.now(timezone.utc).timestamp()), "scheduler.error", f"{type(exc).__name__}:{exc}")
        await asyncio.sleep(max(5, SETTINGS.scheduler_poll_seconds))