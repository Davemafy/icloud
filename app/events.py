from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class EventHub:
    """In-process fan-out hub for dashboard server-sent events.

    The cloud service intentionally runs as a single Uvicorn worker in this build.
    Each browser dashboard gets its own small queue. Slow consumers are coalesced
    rather than allowed to grow memory without bound.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, kind: str = "state") -> None:
        async with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(kind)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(kind)
                except asyncio.QueueFull:
                    pass

    @asynccontextmanager
    async def subscriber(self) -> AsyncIterator[asyncio.Queue[str]]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
        async with self._lock:
            self._subscribers.add(q)
        try:
            yield q
        finally:
            async with self._lock:
                self._subscribers.discard(q)


EVENTS = EventHub()
