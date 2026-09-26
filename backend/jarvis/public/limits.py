"""Rate limiting, and the box the service answers inside.

Both exist for the same reason: this service is a public front end to two APIs
that are free, unauthenticated and somebody else's. The polite way to use them
from an open endpoint is to cache hard, refuse to be a general-purpose proxy,
and cap what one caller can extract.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import Request


class Bbox:
    """Germany, as a rectangle.

    Checked on every coordinate that reaches the service, not only on the ones
    the address picker produced. The URL parameters take lat/lon directly —
    that is the point of them — so the picker is a courtesy and this is the
    rule. A rectangle takes in slivers of every neighbour; that costs nothing,
    because a stop search there finds the German feeds' stops or none.
    """

    def __init__(self, raw: dict[str, float]) -> None:
        self.south = raw.get("south", 47.27)
        self.north = raw.get("north", 55.06)
        self.west = raw.get("west", 5.87)
        self.east = raw.get("east", 15.04)

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east


#: Berlin and Brandenburg — where BVG's API has stops. Inside it BVG stays the
#: first source, because it alone carries the disruption notices; outside it
#: BVG has nothing to say, and asking it anyway would spend its rate limit and,
#: while it is down, ten seconds of every page load on the way to Transitous.
VBB = Bbox({"south": 51.36, "north": 53.56, "west": 11.27, "east": 14.77})


class RateLimiter:
    """A per-caller token bucket, refilling continuously.

    A bucket rather than a fixed window because the traffic here is bursty by
    design: opening the page fires geocode, weather and departures at once, and
    a window counter would either reject that or have to be loose enough to be
    pointless.
    """

    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, who: str) -> bool:
        now = time.monotonic()
        tokens, last = self._buckets.get(who, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens < 1.0:
            self._buckets[who] = (tokens, now)
            return False
        self._buckets[who] = (tokens - 1.0, now)
        return True

    def sweep(self) -> None:
        """Forget callers whose bucket has refilled — they cost nothing to
        recreate, and the dict is keyed on visitor-supplied addresses."""
        now = time.monotonic()
        full = [
            who
            for who, (tokens, last) in self._buckets.items()
            if min(self.capacity, tokens + (now - last) * self.rate) >= self.capacity
        ]
        for who in full:
            self._buckets.pop(who, None)


def caller(request: Request) -> str:
    """Who to rate-limit.

    Behind nginx every request arrives from 127.0.0.1, so the peer address
    would put the whole internet in one bucket. nginx's recommended proxy
    settings set X-Forwarded-For; the first entry is the original client.

    Trusting that header is only safe because nothing but our own nginx can
    reach this port — the service binds loopback.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
