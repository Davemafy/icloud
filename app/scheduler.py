from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable

from .config import SETTINGS
from .db import audit, latest_snapshot
from .timezones import safe_zoneinfo

_last_keys: set[str] = set()


def _times() -> list[tuple[int, int]]:
    out = []
    for x in SETTINGS.session_analysis_times.split(","):
        try:
            hh, mm = x.strip().split(":", 1)
            out.append((int(hh), int(mm)))
        except Exception:
            continue
    return out


def scheduler_status() -> dict:
    tz = safe_zoneinfo(SETTINGS.timezone_name)
    now = datetime.now(tz)
    return {
        "timezone": SETTINGS.timezone_name,
        "timezone_resolved": str(tz),
        "local_time": now.isoformat(),
        "analysis_times": [f"{h:02d}:{m:02d}" for h, m in _times()],
        "poll_seconds": SETTINGS.scheduler_poll_seconds,
    }


def _due_reasons(now_local: datetime) -> list[str]:
    reasons: list[str] = []
    for h, m in _times():
        if now_local.hour == h and now_local.minute == m:
            reasons.append(f"SESSION_{h:02d}{m:02d}")
    snap = latest_snapshot()
    if snap:
        now_utc = int(now_local.astimezone(timezone.utc).timestamp())
        for n in snap.news:
            if n.currency.upper() != "USD" or n.impact.upper() != "HIGH":
                continue
            # T-10 / T+10 analysis, while entries are separately locked T-15.
            for off, tag in [(-10, "PRE_NEWS"), (10, "POST_NEWS")]:
                target = n.ts + off * 60
                if abs(now_utc - target) <= 30:
                    reasons.append(f"{tag}:{n.title or 'USD_HIGH'}")
    return reasons


async def scheduler_loop(run_analysis: Callable[[str], Awaitable[object]]) -> None:
    tz = safe_zoneinfo(SETTINGS.timezone_name)
    while True:
        try:
            now = datetime.now(tz)
            for reason in _due_reasons(now):
                key = f"{now.date()}:{reason}"
                if key in _last_keys:
                    continue
                _last_keys.add(key)
                await run_analysis(reason)
            # prevent unbounded growth
            if len(_last_keys) > 300:
                cutoff = (now.date() - timedelta(days=7)).isoformat()
                for k in list(_last_keys):
                    if k[:10] < cutoff:
                        _last_keys.discard(k)
        except Exception as exc:
            audit(int(datetime.now(timezone.utc).timestamp()), "scheduler.error", f"{type(exc).__name__}:{exc}")
        await asyncio.sleep(max(5, SETTINGS.scheduler_poll_seconds))
