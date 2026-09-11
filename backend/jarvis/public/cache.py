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

**A dead upstream gets the last good answer, not an error.** An entry stays in
the dict for a grace period after it expires, and `get(stale_ok=True)` hands it
back when production fails. The age comes back with it and is not optional: the
panel's whole freezing discipline is computed from when the data was fetched, so
serving twenty-minute-old departures as if they arrived just now would restart
countdowns that ought to be frozen. The caller passes the age on to the browser,
which subtracts it and carries on being honest for free.

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
    def __init__(self, seconds: int, *, grace: int = 3600) -> None:
        self.seconds = seconds
        #: How long an expired entry is kept around to be served during an
        #: outage. Bounded, because the keys are visitor-supplied coordinates
        #: and an unbounded graveyard is a slow memory leak with extra steps.
        self.grace = grace
        self._entries: dict[Any, tuple[float, Any]] = {}
        self._locks: dict[Any, asyncio.Lock] = {}

    def peek(self, key: Any) -> Any | None:
        entry = self._entries.get(key)
        if entry is None or time.monotonic() - entry[0] > self.seconds:
            return None
        return entry[1]

    def _expired(self, key: Any) -> tuple[Any, float] | None:
        """The last good value and its age, while it is still worth offering."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        age = time.monotonic() - entry[0]
        return (entry[1], age) if age <= self.seconds + self.grace else None

    async def get(
        self,
        key: Any,
        produce: Callable[[], Awaitable[Any]],
        *,
        stale_ok: bool = False,
    ) -> tuple[Any, float]:
        """The value and its age in seconds. Age is 0 for a fresh answer."""
        hit = self.peek(key)
        if hit is not None:
            return hit, 0.0

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Re-check: whoever held the lock has just filled it in.
            hit = self.peek(key)
            if hit is not None:
                return hit, 0.0
            try:
                value = await produce()
            except Exception:
                # Something old beats nothing, but only if the caller has said
                # that its payload can survive being late — and only ever with
                # the age attached.
                if stale_ok:
                    stale = self._expired(key)
                    if stale is not None:
                        return stale
                raise
            self._entries[key] = (time.monotonic(), value)
            return value, 0.0

    def sweep(self) -> None:
        """Drop expired entries and their locks.

        Worth doing, because the keys are visitor-supplied: every distinct
        rounded coordinate anyone ever asks for would otherwise stay in the dict
        for the life of the process, and so would its lock.
        """
        now = time.monotonic()
        cutoff = self.seconds + self.grace
        stale = [k for k, (at, _) in self._entries.items() if now - at > cutoff]
        for key in stale:
            self._entries.pop(key, None)
            lock = self._locks.get(key)
            if lock is not None and not lock.locked():
                self._locks.pop(key, None)
