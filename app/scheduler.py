from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import SETTINGS
from .db import DB
from .events import EVENTS
from .news import refresh_news, stored_news
from .service import load_analysis_snapshot, load_latest_full_snapshot, load_latest_snapshot, run_production_analysis


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":", 1)
    return int(h), int(m)


def _configured_sessions() -> dict[str, str]:
    return {
        "ASIA": SETTINGS.session_asia_start,
        "LONDON": SETTINGS.session_london_start,
        "NEW_YORK": SETTINGS.session_newyork_start,
    }


def _session_windows(now_utc: datetime | None = None):
    """Yield nearby session pre-run windows in configured local time.

    Yesterday/today/tomorrow are inspected because the pre-Asia run normally
    occurs on the calendar day before the Asia session start.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    tz = ZoneInfo(SETTINGS.timezone_name)
    local = now_utc.astimezone(tz)
    for name, hhmm in _configured_sessions().items():
        h, m = _parse_hhmm(hhmm)
        base = local.replace(hour=h, minute=m, second=0, microsecond=0)
        for day_offset in (-1, 0, 1):
            start = base + timedelta(days=day_offset)
            run_at = start - timedelta(minutes=SETTINGS.session_lead_minutes)
            window_end = run_at + timedelta(minutes=SETTINGS.session_catchup_minutes)
            yield name, start, run_at, window_end, local


def _session_starts(now_utc: datetime | None = None):
    """Return nearby configured session starts, chronologically."""
    now_utc = now_utc or datetime.now(timezone.utc)
    tz = ZoneInfo(SETTINGS.timezone_name)
    local = now_utc.astimezone(tz)
    starts: list[tuple[datetime, str]] = []
    for day_offset in (-1, 0, 1, 2):
        day = local.date() + timedelta(days=day_offset)
        for name, hhmm in _configured_sessions().items():
            h, m = _parse_hhmm(hhmm)
            starts.append((datetime(day.year, day.month, day.day, h, m, tzinfo=tz), name))
    starts.sort(key=lambda x: x[0])
    return starts, local


def active_session(now_utc: datetime | None = None) -> dict | None:
    """Return the active trading-session context.

    A session is active from its configured start until the next configured
    session start. This is used only for scheduler recovery; it does not change
    the market-session label supplied by the MT5 Data Bridge.
    """
    starts, local = _session_starts(now_utc)
    previous = None
    for i, (start, name) in enumerate(starts):
        if start <= local:
            previous = (i, start, name)
        else:
            break
    if previous is None:
        return None
    i, start, name = previous
    if i + 1 >= len(starts):
        return None
    end = starts[i + 1][0]
    run_at = start - timedelta(minutes=SETTINGS.session_lead_minutes)
    window_end = run_at + timedelta(minutes=SETTINGS.session_catchup_minutes)
    return {
        "session": name,
        "session_start": start,
        "session_end": end,
        "scheduled_analysis_at": run_at,
        "catchup_until": window_end,
        "run_key": f"session:{name}:{start.date().isoformat()}",
    }


def _pre_session_candidates(now_utc: datetime | None = None) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for name, start, run_at, window_end, local in _session_windows(now_utc):
        if run_at <= local <= window_end:
            key = f"session:{name}:{start.date().isoformat()}"
            if key not in seen:
                out.append({
                    "run_key": key,
                    "session": name,
                    "mode": "pre_session",
                    "session_start": start,
                    "scheduled_analysis_at": run_at,
                    "catchup_until": window_end,
                })
                seen.add(key)
    return out


def session_run_candidates(now_utc: datetime | None = None) -> list[dict]:
    """Return the session analysis that should run now.

    Priority is deliberate:
      1) an upcoming session inside its pre-session/catch-up window;
      2) otherwise, recover the currently active session if its run was missed.

    This prevents a late recovery of the outgoing session from competing with a
    more relevant pre-session analysis (for example London recovery at 12:55
    when New York is already due).
    """
    pre = _pre_session_candidates(now_utc)
    if pre:
        return pre

    if not SETTINGS.session_active_recovery:
        return []

    current = active_session(now_utc)
    if current is None:
        return []
    return [{
        "run_key": current["run_key"],
        "session": current["session"],
        "mode": "active_recovery",
        "session_start": current["session_start"],
        "scheduled_analysis_at": current["scheduled_analysis_at"],
        "catchup_until": current["catchup_until"],
        "session_end": current["session_end"],
    }]


def session_run_keys(now_utc: datetime | None = None) -> list[tuple[str, str]]:
    """Compatibility wrapper used by tests and older callers."""
    return [(x["run_key"], x["session"]) for x in session_run_candidates(now_utc)]


def session_context_to_satisfy(now_utc: datetime | None = None) -> dict | None:
    """Pick the session key that a successful manual analysis may satisfy.

    If an upcoming session is already in its pre-session window, that upcoming
    session wins. Otherwise the currently active session is used.
    """
    pre = _pre_session_candidates(now_utc)
    if pre:
        return pre[0]
    if SETTINGS.session_active_recovery:
        current = active_session(now_utc)
        if current:
            return {
                "run_key": current["run_key"],
                "session": current["session"],
                "mode": "manual_active_session",
                "session_start": current["session_start"],
                "scheduled_analysis_at": current["scheduled_analysis_at"],
                "catchup_until": current["catchup_until"],
                "session_end": current["session_end"],
            }
    return None


def mark_manual_analysis_satisfies_session(result, reason: str, now_utc: datetime | None = None) -> str | None:
    """Count a completed manual analysis as satisfying the relevant session.

    This avoids an unnecessary duplicate AI call immediately after an operator
    has already generated a fresh, approved plan for that session.
    """
    ctx = session_context_to_satisfy(now_utc)
    if not ctx:
        return None
    run_key = ctx["run_key"]
    if DB.scheduler_ran(run_key):
        return run_key
    mode = getattr(getattr(result, "ea_mode", None), "value", getattr(result, "ea_mode", "UNKNOWN"))
    details = (
        f"{ctx['session']} satisfied by manual analysis_id={getattr(result, 'analysis_id', 'unknown')} "
        f"mode={mode} ai={getattr(result, 'ai_used', False)} reason={reason}"
    )
    DB.mark_scheduler_run(run_key, "session_manual", "success", details)
    DB.audit("session.manual_satisfied", "scheduler", f"run_key={run_key} {details}")
    return run_key


def _major_news_clusters() -> list[dict]:
    """Group simultaneous high-impact USD events into one market revalidation.

    CPI variants, PPI + claims, or other releases can share the exact same
    timestamp. They create one repricing event in the market, so one deep
    D1/H4/H1 zone revalidation per timestamp is both sufficient and materially
    more efficient than spending several identical AI calls back-to-back.
    """
    grouped: dict[str, dict] = {}
    for e in stored_news():
        if e.currency.upper() != "USD" or e.impact.upper() != "HIGH":
            continue
        ts = e.ts.astimezone(timezone.utc)
        key = ts.isoformat()
        bucket = grouped.setdefault(key, {"event_ts": ts, "events": []})
        bucket["events"].append(e)

    out: list[dict] = []
    for key, bucket in grouped.items():
        events = bucket["events"]
        titles = sorted({e.title for e in events})
        out.append({
            "cluster_key": str(int(bucket["event_ts"].timestamp())),
            "event_ts": bucket["event_ts"],
            "title": " + ".join(titles),
            "event_ids": [e.event_id for e in events],
        })
    return sorted(out, key=lambda x: x["event_ts"])


def pre_news_run_keys(now_utc: datetime | None = None) -> list[tuple[str, str, datetime]]:
    """Return T-10 major-news zone revalidations due before release.

    The target is NEWS_PRE_ANALYSIS_MINUTES before the release. Retries are
    allowed only before the event itself; a missed pre-news analysis is never
    executed after the release under the wrong market regime.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    out = []
    for cluster in _major_news_clusters():
        event_ts = cluster["event_ts"]
        run_at = event_ts - timedelta(minutes=SETTINGS.news_pre_analysis_minutes)
        configured_end = run_at + timedelta(minutes=SETTINGS.pre_news_catchup_minutes)
        window_end = min(configured_end, event_ts - timedelta(seconds=1))
        if run_at <= now_utc <= window_end:
            out.append((f"news_pre:{cluster['cluster_key']}", cluster["title"], event_ts))
    return out


def post_news_run_keys(now_utc: datetime | None = None) -> list[tuple[str, str, datetime]]:
    """Return T+10 major-news zone revalidations with a retry window."""
    now_utc = now_utc or datetime.now(timezone.utc)
    out = []
    for cluster in _major_news_clusters():
        event_ts = cluster["event_ts"]
        run_at = event_ts + timedelta(minutes=SETTINGS.news_post_analysis_minutes)
        window_end = run_at + timedelta(minutes=SETTINGS.post_news_catchup_minutes)
        if run_at <= now_utc <= window_end:
            out.append((f"news_post:{cluster['cluster_key']}", cluster["title"], event_ts))
    return out


def _snapshot_age_seconds(now_utc: datetime, snap) -> float:
    generated = snap.generated_at
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return max(0.0, (now_utc - generated.astimezone(timezone.utc)).total_seconds())


def scheduler_status(now_utc: datetime | None = None) -> dict:
    now_utc = now_utc or datetime.now(timezone.utc)
    tz = ZoneInfo(SETTINGS.timezone_name)
    local = now_utc.astimezone(tz)
    current = active_session(now_utc)
    pre_due = {x["run_key"] for x in _pre_session_candidates(now_utc)}
    rows = []

    for name in ("ASIA", "LONDON", "NEW_YORK"):
        chosen = None

        # 1) Current active session stays visible instead of jumping directly to
        # tomorrow after its narrow pre-session catch-up window expires.
        if current and current["session"] == name:
            chosen = {
                "session": name,
                "session_start": current["session_start"],
                "scheduled_analysis_at": current["scheduled_analysis_at"],
                "catchup_until": current["catchup_until"],
                "session_end": current["session_end"],
                "run_key": current["run_key"],
                "window_active": current["run_key"] in pre_due,
                "recovery_active": current["run_key"] not in pre_due,
            }

        # 2) If this named session is currently in an upcoming pre-session window,
        # that is more relevant than the active-session row above.
        for cand in _pre_session_candidates(now_utc):
            if cand["session"] == name:
                chosen = {
                    **cand,
                    "window_active": True,
                    "recovery_active": False,
                    "session_end": None,
                }
                break

        # 3) Otherwise display the next future run.
        if chosen is None:
            candidates = []
            for n, start, run_at, window_end, _ in _session_windows(now_utc):
                if n != name or run_at < local:
                    continue
                key = f"session:{name}:{start.date().isoformat()}"
                candidates.append((abs((run_at - local).total_seconds()), start, run_at, window_end, key))
            if candidates:
                _, start, run_at, window_end, key = sorted(candidates, key=lambda x: x[0])[0]
                chosen = {
                    "session": name,
                    "session_start": start,
                    "scheduled_analysis_at": run_at,
                    "catchup_until": window_end,
                    "session_end": None,
                    "run_key": key,
                    "window_active": False,
                    "recovery_active": False,
                }

        if chosen:
            completed = DB.scheduler_ran(chosen["run_key"])
            if completed:
                status = "DONE"
            elif chosen.get("window_active"):
                status = "DUE_RETRYING"
            elif chosen.get("recovery_active") and SETTINGS.session_active_recovery:
                status = "RECOVERY_DUE"
            else:
                status = "WAITING"
            # Dashboard/SSE payloads must remain JSON-serializable.
            row = dict(chosen)
            for field in ("session_start", "scheduled_analysis_at", "catchup_until", "session_end"):
                value = row.get(field)
                if isinstance(value, datetime):
                    row[field] = value.isoformat()
            row["completed"] = completed
            row["status"] = status
            rows.append(row)

    return {
        "timezone": SETTINGS.timezone_name,
        "now_local": local.isoformat(),
        "session_lead_minutes": SETTINGS.session_lead_minutes,
        "session_catchup_minutes": SETTINGS.session_catchup_minutes,
        "session_active_recovery": SETTINGS.session_active_recovery,
        "snapshot_max_age_seconds": SETTINGS.session_snapshot_max_age_seconds,
        "news_pre_analysis_minutes": SETTINGS.news_pre_analysis_minutes,
        "news_post_analysis_minutes": SETTINGS.news_post_analysis_minutes,
        "news_pre_blackout_minutes": SETTINGS.news_pre_blackout_minutes,
        "news_post_cooldown_minutes": SETTINGS.news_post_cooldown_minutes,
        "active_session": current["session"] if current else None,
        "sessions": rows,
        "recent_runs": DB.list_scheduler_runs(12),
    }


async def scheduler_loop():
    last_news_poll: datetime | None = None
    while True:
        now = datetime.now(timezone.utc)
        try:
            if SETTINGS.news_provider != "manual" and (
                last_news_poll is None
                or (now - last_news_poll).total_seconds() >= SETTINGS.news_poll_minutes * 60
            ):
                try:
                    await refresh_news()
                except Exception as exc:
                    DB.audit("news.refresh_failed", "scheduler", str(exc))
                last_news_poll = now

            for cand in session_run_candidates(now):
                run_key = cand["run_key"]
                name = cand["session"]
                mode = cand["mode"]
                if DB.scheduler_ran(run_key):
                    continue

                live = load_latest_snapshot()
                if live is None:
                    DB.audit("session.waiting", "scheduler", f"{name}/{mode}: no live snapshot yet; run_key={run_key}")
                    continue
                age = _snapshot_age_seconds(now, live)
                if age > SETTINGS.session_snapshot_max_age_seconds:
                    DB.audit(
                        "session.waiting", "scheduler",
                        f"{name}/{mode}: live snapshot stale age={age:.0f}s > {SETTINGS.session_snapshot_max_age_seconds}s; run_key={run_key}",
                    )
                    continue
                snap = load_analysis_snapshot()
                if snap is None:
                    DB.audit(
                        "session.waiting", "scheduler",
                        f"{name}/{mode}: waiting for FULL_HISTORY context sync from MT5; run_key={run_key}",
                    )
                    continue
                full = load_latest_full_snapshot()
                required_full_at = cand["scheduled_analysis_at"].astimezone(timezone.utc) - timedelta(seconds=90)
                if full is None or full.generated_at.astimezone(timezone.utc) < required_full_at:
                    got = "none" if full is None else f"{full.generated_at.isoformat()} reason={full.snapshot_reason}"
                    DB.audit(
                        "session.waiting", "scheduler",
                        f"{name}/{mode}: waiting for session-fresh FULL_HISTORY; required>={required_full_at.isoformat()} got={got}; run_key={run_key}",
                    )
                    continue

                try:
                    # The scheduler target is authoritative for a pre-session plan.
                    # At 07:50 WAT the wall-clock bridge session is still ASIA, but
                    # the analysis being prepared is LONDON; label it accordingly.
                    snap = snap.model_copy(deep=True)
                    snap.session = name
                    reason = f"pre_session:{name}:auto" if mode == "pre_session" else f"session_recovery:{name}:auto"
                    result = await run_production_analysis(snap, reason=reason)
                    DB.mark_scheduler_run(
                        run_key, "session", "success",
                        f"{name} mode={mode} analysis_id={result.analysis_id} ea={result.ea_mode.value} ai={result.ai_used}",
                    )
                    await EVENTS.publish("scheduler")
                    DB.audit(
                        "session.analysis_success", "scheduler",
                        f"{name}: mode={mode} run_key={run_key} analysis_id={result.analysis_id} ea={result.ea_mode.value}",
                    )
                except Exception as exc:
                    # Failed attempts remain auditable, but only success suppresses
                    # later retries/recovery for this session key.
                    DB.mark_scheduler_run(run_key, "session", "failed", f"{name} mode={mode}: {exc}")
                    await EVENTS.publish("scheduler")
                    DB.audit("session.analysis_failed", "scheduler", f"{name}/{mode}: {exc}")

            # Major USD news is revalidated twice: around T-10 and T+10.
            # M15 is used only inside the cloud zone-qualification pass; once a
            # zone is published, M1 remains the sole execution trigger.
            for run_key, title, event_ts in pre_news_run_keys(now):
                if DB.scheduler_ran(run_key):
                    continue
                live = load_latest_snapshot()
                snap = load_analysis_snapshot()
                if live is None:
                    DB.audit("pre_news.waiting", "scheduler", f"{title}: no live snapshot yet")
                    continue
                age = _snapshot_age_seconds(now, live)
                if age > SETTINGS.session_snapshot_max_age_seconds:
                    DB.audit("pre_news.waiting", "scheduler", f"{title}: waiting for fresher live snapshot age={age:.0f}s")
                    continue
                if snap is None:
                    DB.audit("pre_news.waiting", "scheduler", f"{title}: waiting for FULL_HISTORY context")
                    continue
                full = load_latest_full_snapshot()
                target_at = event_ts.astimezone(timezone.utc) - timedelta(minutes=SETTINGS.news_pre_analysis_minutes)
                required_full_at = target_at - timedelta(seconds=90)
                if full is None or full.generated_at.astimezone(timezone.utc) < required_full_at:
                    got = "none" if full is None else f"{full.generated_at.isoformat()} reason={full.snapshot_reason}"
                    DB.audit(
                        "pre_news.waiting", "scheduler",
                        f"{title}: waiting for T-10 FULL_HISTORY; required>={required_full_at.isoformat()} got={got}",
                    )
                    continue
                try:
                    result = await run_production_analysis(snap, reason=f"pre_news:{title}:auto")
                    DB.mark_scheduler_run(
                        run_key, "pre_news", "success",
                        f"{title} analysis_id={result.analysis_id} mode={result.ea_mode.value} ai={result.ai_used}",
                    )
                    DB.audit(
                        "pre_news.analysis_success", "scheduler",
                        f"{title}: run_key={run_key} analysis_id={result.analysis_id} ea={result.ea_mode.value}",
                    )
                    await EVENTS.publish("scheduler")
                except Exception as exc:
                    DB.mark_scheduler_run(run_key, "pre_news", "failed", str(exc))
                    DB.audit("pre_news.analysis_failed", "scheduler", f"{title}: {exc}")
                    await EVENTS.publish("scheduler")

            for run_key, title, event_ts in post_news_run_keys(now):
                if DB.scheduler_ran(run_key):
                    continue
                live = load_latest_snapshot()
                snap = load_analysis_snapshot()
                if live and snap and live.generated_at.astimezone(timezone.utc) >= event_ts.astimezone(timezone.utc):
                    age = _snapshot_age_seconds(now, live)
                    if age > SETTINGS.session_snapshot_max_age_seconds:
                        DB.audit("post_news.waiting", "scheduler", f"{title}: waiting for fresher live snapshot age={age:.0f}s")
                        continue
                    full = load_latest_full_snapshot()
                    required_full_at = event_ts.astimezone(timezone.utc) + timedelta(minutes=SETTINGS.news_post_analysis_minutes)
                    if full is None or full.generated_at.astimezone(timezone.utc) < required_full_at:
                        DB.audit("post_news.waiting", "scheduler", f"{title}: waiting for T+10 FULL_HISTORY sync after {required_full_at.isoformat()}")
                        continue
                    try:
                        result = await run_production_analysis(snap, reason=f"post_news:{title}:auto")
                        DB.mark_scheduler_run(
                            run_key, "post_news", "success",
                            f"{title} analysis_id={result.analysis_id} mode={result.ea_mode.value} ai={result.ai_used}",
                        )
                        DB.audit(
                            "post_news.analysis_success", "scheduler",
                            f"{title}: run_key={run_key} analysis_id={result.analysis_id} ea={result.ea_mode.value}",
                        )
                        await EVENTS.publish("scheduler")
                    except Exception as exc:
                        DB.mark_scheduler_run(run_key, "post_news", "failed", str(exc))
                        DB.audit("post_news.analysis_failed", "scheduler", f"{title}: {exc}")
                        await EVENTS.publish("scheduler")
                elif live is None:
                    DB.audit("post_news.waiting", "scheduler", f"{title}: no live snapshot yet")
                elif snap is None:
                    DB.audit("post_news.waiting", "scheduler", f"{title}: waiting for FULL_HISTORY context")
                else:
                    DB.audit("post_news.waiting", "scheduler", f"{title}: waiting for post-release snapshot")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            DB.audit("scheduler.error", "scheduler", str(exc))
        await asyncio.sleep(SETTINGS.scheduler_poll_seconds)
