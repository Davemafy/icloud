from __future__ import annotations

from datetime import timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def safe_zoneinfo(name: str):
    """Return an IANA timezone without allowing a missing Windows tz DB to crash the app.

    Python on some Windows installations has no system IANA database. The `tzdata`
    dependency normally fixes that. This fallback is intentionally narrow: Africa/Lagos
    is UTC+1 year-round and has no DST. Unknown names fall back to UTC rather than crash
    the dashboard/SSE scheduler.
    """
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Africa/Lagos":
            return timezone(timedelta(hours=1), name="WAT")
        return timezone.utc
