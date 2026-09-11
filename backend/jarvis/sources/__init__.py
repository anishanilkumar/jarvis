"""Where departure data comes from, and what to do when it stops coming.

On 7 September 2026 `v6.bvg.transport.rest` went down for hours — first
intermittently, then completely — and took the board, the address picker and
the wall with it. Its two sibling instances went down at the same moment,
because all three hostnames are one box. There is no fallback to be had inside
that family, and no status page to promise there won't be a next time.

So: more than one source, from operators who fail independently. BVG stays
primary because only HAFAS carries the disruption remarks. Transitous is a
different organisation on different infrastructure reading a different data
pipeline (GTFS-RT rather than HAFAS), which is the property that matters — two
copies of the same upstream would have failed together, exactly as vbb and db
did.

**The interface is BVG's wire format, not a neutral one of our own.** Every
source returns precisely what `v6.bvg.transport.rest` would have returned, and
everything downstream — `shape_board`, `shape_hit`, `board_for`, the whole
panel — never learns that a second source exists. The alternative was a
normalised format in the middle and a rewrite of the shaping to read it, which
is a much larger change to code that is correct today, in order to serve a path
taken only when the primary is broken. Translation lives at the edge, once per
source, in the module that already has to know that source's peculiarities.

What is honestly lost on the fallback path is the disruption text: Transitous
has no alerts field, so `warnings` comes back empty. The tile says which source
it is on for exactly that reason — a board quietly missing its disruptions is
the same kind of silent lie the frozen countdowns exist to prevent.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import httpx

from jarvis.sources import bvg, transitous

log = logging.getLogger(__name__)

#: Preference order. First healthy source wins, so this is also the quality
#: order: BVG carries remarks and platform detail that Transitous does not.
SOURCES: tuple[ModuleType, ...] = (bvg, transitous)


class NoSource(httpx.HTTPError):
    """Every source failed.

    An httpx.HTTPError subclass on purpose: the public app already turns those
    into a 502 with the reason attached, and the wall's scheduler already backs
    off on any exception. Neither needed teaching about this.
    """


@dataclass
class Breaker:
    """Skip an upstream that is known to be down, instead of waiting for it.

    A plain try/except is not enough on its own. Through the September outage
    every BVG call sat for ten to twenty-five seconds before failing, so a
    dashboard that "fell back correctly" still took half a minute to draw — the
    fallback was working and the page was unusable. After `threshold`
    consecutive failures the source is skipped outright, and the page renders
    from the second source at full speed.

    Half-open rather than simply timed: when the cooldown expires exactly one
    request is allowed through to test the water, and if it fails the breaker
    shuts again immediately rather than spending another `threshold` slow
    requests rediscovering what it already knew.
    """

    name: str
    threshold: int = 3
    cooldown: float = 120.0
    failures: int = 0
    opened_at: float | None = None
    probing: bool = False

    def ready(self) -> bool:
        if self.opened_at is None:
            return True
        if time.monotonic() - self.opened_at < self.cooldown:
            return False
        self.probing = True
        return True

    def succeeded(self) -> None:
        if self.opened_at is not None:
            log.info("source %s recovered", self.name)
        self.failures = 0
        self.opened_at = None
        self.probing = False

    def failed(self) -> None:
        self.failures += 1
        if self.probing or self.failures >= self.threshold:
            if self.opened_at is None:
                log.warning(
                    "source %s failing (%d consecutive) — skipping for %.0fs",
                    self.name,
                    self.failures,
                    self.cooldown,
                )
            self.opened_at = time.monotonic()
            self.probing = False


#: Process-wide, and deliberately not per-request or per-board. The whole point
#: is that one board discovering BVG is down spares the other three the wait.
_breakers: dict[str, Breaker] = {}


def breaker(name: str) -> Breaker:
    return _breakers.setdefault(name, Breaker(name))


def health() -> dict[str, bool]:
    """Which sources are currently being tried, for /api/health."""
    return {source.NAME: breaker(source.NAME).opened_at is None for source in SOURCES}


def _ordered() -> list[ModuleType]:
    """Sources to try, healthy ones first.

    Tripped sources go to the back rather than being dropped: if every source
    is tripped the request should still be attempted rather than failing
    instantly on a stale opinion, and the ordering alone is enough to make the
    healthy path fast.
    """
    healthy = [s for s in SOURCES if breaker(s.NAME).ready()]
    tripped = [s for s in SOURCES if s not in healthy]
    return healthy + tripped


async def attempt(
    operation: str, *, only: str | None = None, **kwargs: Any
) -> tuple[str, Any]:
    """Run one operation against each source until one answers.

    Returns the name of the source that answered along with its value, because
    every caller has to pass that up to the panel — "via transitous" is not a
    detail, it is the difference between a board with disruption notices and a
    board without them.

    `only` pins the request to one source, and exists because stop ids do not
    survive a change of source. A caller that has already looked stops up holds
    ids that mean something to exactly one API; letting the other one try them
    would not fail, it would succeed emptily, and an empty board is drawn as a
    stop where nothing runs rather than as an error. Better to fail the request.
    """
    reasons: list[str] = []
    candidates = _ordered()
    if only is not None:
        candidates = [source for source in candidates if source.NAME == only]

    for source in candidates:
        state = breaker(source.NAME)
        try:
            value = await getattr(source, operation)(**kwargs)
        except Exception as exc:  # noqa: BLE001 — any failure means "try the next one"
            state.failed()
            reasons.append(f"{source.NAME}: {type(exc).__name__}")
            continue
        state.succeeded()
        return source.NAME, value

    raise NoSource(f"no source answered ({', '.join(reasons)})")
