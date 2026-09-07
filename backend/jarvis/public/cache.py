"""A TTL cache with single-flight, in process memory.

Two properties matter more than the storage:

**Coordinates are rounded before they become a key.** Three decimals is about
110 metres, so a whole street shares one upstream call. Without that, a public
service makes one request per visitor per refresh and the shared answer is
never shared.

**Concurrent misses collapse into one upstream call.** The obvious dict-with-
timestamps lets twenty simultaneous visitors to the same stop each start their
own request the moment the entry expires — the load spike lands precisely when
the cache is least able to absorb it. A per-key lock means the first caller
fetches and the rest wait for it.

Losing everything on restart is correct here. There is no state to preserve;
the worst case is one cold minute.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable


def round_coords(lat: float, lon: float, places: int = 3) -> tuple[float, float]:
    """A cache key from a location. ~110m at three decimals in Berlin."""
    return (round(lat, places), round(lon, places))


class TTLCache:
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        self._entries: dict[Any, tuple[float, Any]] = {}
        self._locks: dict[Any, asyncio.Lock] = {}

    def peek(self, key: Any) -> Any | None:
        entry = self._entries.get(key)
        if entry is None or time.monotonic() - entry[0] > self.seconds:
            return None
        return entry[1]

    async def get(self, key: Any, produce: Callable[[], Awaitable[Any]]) -> Any:
        hit = self.peek(key)
        if hit is not None:
            return hit

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Re-check: whoever held the lock has just filled it in.
            hit = self.peek(key)
            if hit is not None:
                return hit
            value = await produce()
            self._entries[key] = (time.monotonic(), value)
            return value

    def sweep(self) -> None:
        """Drop expired entries and their locks.

        Worth doing, because the keys are visitor-supplied: every distinct
        rounded coordinate anyone ever asks for would otherwise stay in the dict
        for the life of the process, and so would its lock.
        """
        now = time.monotonic()
        stale = [k for k, (at, _) in self._entries.items() if now - at > self.seconds]
        for key in stale:
            self._entries.pop(key, None)
            lock = self._locks.get(key)
            if lock is not None and not lock.locked():
                self._locks.pop(key, None)
