from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import httpx

from .config import SETTINGS
from .db import DB
from .models import NewsEvent


class NewsProviderError(RuntimeError):
    pass


async def fetch_tradingeconomics_high_impact_usd() -> list[NewsEvent]:
    if not SETTINGS.tradingeconomics_api_key:
        raise NewsProviderError("TRADINGECONOMICS_API_KEY is not configured")
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=1)).date().isoformat()
    end = (now + timedelta(days=3)).date().isoformat()
    url = f"https://api.tradingeconomics.com/calendar/country/united%20states/{start}/{end}"
    params = {"c": SETTINGS.tradingeconomics_api_key, "importance": 3, "f": "json"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, params=params)
    if r.status_code >= 400:
        raise NewsProviderError(f"TradingEconomics error {r.status_code}: {r.text[:300]}")
    out: list[NewsEvent] = []
    for item in r.json():
        raw = item.get("Date")
        if not raw:
            continue
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        actual = item.get("Actual")
        released = bool(actual not in (None, "")) and ts <= now
        out.append(NewsEvent(
            event_id=str(item.get("CalendarId") or item.get("CalendarID") or f"TE-{raw}-{item.get('Event','')}")[:180],
            ts=ts, currency="USD", impact="HIGH", title=item.get("Event") or item.get("Category") or "US high-impact event",
            released=released, actual=None if actual in (None, "") else str(actual),
            forecast=None if item.get("Forecast") in (None, "") else str(item.get("Forecast")),
            previous=None if item.get("Previous") in (None, "") else str(item.get("Previous")),
            source="tradingeconomics",
        ))
    return out


async def refresh_news() -> list[NewsEvent]:
    if SETTINGS.news_provider == "tradingeconomics":
        events = await fetch_tradingeconomics_high_impact_usd()
        for event in events:
            DB.upsert_news(event.model_dump(mode="json"))
        DB.audit("news.refresh", "scheduler", f"stored={len(events)} provider=tradingeconomics")
        return events
    if SETTINGS.news_provider == "mt5_calendar":
        # The MT5 Data Bridge pushes the platform economic calendar with every
        # market snapshot. There is nothing to pull from the cloud side here.
        events = stored_news()
        DB.audit("news.refresh", "scheduler", f"stored={len(events)} provider=mt5_calendar")
        return events
    return []


def stored_news() -> list[NewsEvent]:
    events = []
    for row in DB.list_news(100):
        try:
            import json
            events.append(NewsEvent.model_validate(json.loads(row["payload"])))
        except Exception:
            continue
    return events


def blackout_state(now: datetime | None = None) -> tuple[bool, str, list[NewsEvent]]:
    now = now or datetime.now(timezone.utc)
    active = []
    reasons = []
    for e in stored_news():
        if e.currency.upper() != "USD" or e.impact.upper() != "HIGH":
            continue
        pre = e.ts - timedelta(minutes=SETTINGS.news_pre_blackout_minutes)
        post = e.ts + timedelta(minutes=SETTINGS.news_post_cooldown_minutes)
        if pre <= now <= post:
            active.append(e)
            reasons.append(f"{e.title} @ {e.ts.isoformat()}")
    return bool(active), "; ".join(reasons), active
