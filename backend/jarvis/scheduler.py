"""One refresh loop per provider, each on its own TTL.

Design rule: a provider failing must never remove data from the panel. It keeps
its last good value, gains an `error` and a `stale` flag, and backs off so a
dead upstream isn't hammered. Recovery is automatic and needs no touch.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Callable, Awaitable

from jarvis.cache import Cache
from jarvis.registry import Provider

log = logging.getLogger(__name__)

#: Back-off ceiling. Ten minutes is long enough to stop pestering a broken API,
#: short enough that recovery feels automatic rather than requiring a restart.
MAX_BACKOFF = 600.0


class ProviderState:
    """Everything the panel needs to render one tile honestly."""

    def __init__(self, slug: str, policy: dict[str, int]) -> None:
        self.slug = slug
        self.ttl: int = policy["ttl"]
        self.stale_after: int = policy["stale_after"]
        self.useful_for: int = policy["useful_for"]

        self.data: dict[str, Any] | None = None
        self.fetched_at: float | None = None
        self.error: str | None = None
        self.consecutive_failures = 0

    @property
    def stale(self) -> bool:
        """True when the data we hold is older than this provider tolerates."""
        if self.fetched_at is None:
            return True
        if self.stale_after <= 0:
            return False
        return (time.time() - self.fetched_at) > self.stale_after

    def as_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "fetched_at": self.fetched_at,
            "stale": self.stale,
            "error": self.error,
            # Sent so the tablet can enforce expiry itself while the Pi is
            # unreachable and can't tell it anything.
            "useful_for": self.useful_for,
        }


class Scheduler:
    """Owns the provider instances, their refresh tasks and the shared state."""

    def __init__(self, cache: Cache, on_update: Callable[[str], Awaitable[None]]) -> None:
        self.cache = cache
        self.on_update = on_update
        self.providers: dict[str, Provider] = {}
        self.states: dict[str, ProviderState] = {}
        self._tasks: list[asyncio.Task[None]] = []

    def register(self, provider: Provider, policy: dict[str, int]) -> None:
        slug = provider.slug
        self.providers[slug] = provider
        state = ProviderState(slug, policy)

        # Seed from disk so the very first paint after a restart has content.
        if cached := self.cache.get(slug):
            state.data = cached["data"]
            state.fetched_at = cached["fetched_at"]

        self.states[slug] = state

    def start(self) -> None:
        for slug, provider in self.providers.items():
            if not provider.polls or self.states[slug].ttl <= 0:
                continue
            self._tasks.append(asyncio.create_task(self._loop(slug), name=f"refresh:{slug}"))
        log.info("scheduler started with %d polling providers", len(self._tasks))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def refresh(self, slug: str) -> None:
        """Fetch one provider now. Used by the loop, by actions, and at startup."""
        provider = self.providers[slug]
        state = self.states[slug]
        try:
            data = await provider.fetch()
        except Exception as exc:  # noqa: BLE001 — any failure is the same to us
            state.consecutive_failures += 1
            state.error = f"{type(exc).__name__}: {exc}"
            log.warning(
                "%s fetch failed (%d in a row): %s", slug, state.consecutive_failures, exc
            )
        else:
            state.data = data
            state.fetched_at = time.time()
            state.error = None
            state.consecutive_failures = 0
            self.cache.put(slug, data, state.fetched_at)

        await self.on_update(slug)

    def _delay_for(self, state: ProviderState) -> float:
        """Normal TTL, or exponential back-off after failures.

        The cap is per-provider, not global. A brief uplink blip used to be able
        to push a fast-refreshing tile into a back-off longer than its own
        `useful_for` — so the tile went dark waiting to retry, long after the
        network had recovered. Observed live: departures (ttl 30) reached the
        600s ceiling, exactly its expiry. So a provider may never back off past
        a quarter of the window in which its data stays meaningful.

        Jitter keeps several providers that failed together from retrying in
        lockstep afterwards.
        """
        if state.consecutive_failures == 0:
            return float(state.ttl)

        cap = MAX_BACKOFF
        if state.useful_for > 0:
            # Still allow a few multiples of ttl, so a genuinely dead upstream
            # isn't hammered at its normal rate.
            cap = min(cap, max(4 * state.ttl, state.useful_for / 4))

        backoff = min(state.ttl * (2 ** state.consecutive_failures), cap)
        return backoff * (0.8 + 0.4 * random.random())

    async def _loop(self, slug: str) -> None:
        state = self.states[slug]
        # Stagger first fetches so startup doesn't fire every upstream at once.
        await asyncio.sleep(random.random() * 2)
        while True:
            await self.refresh(slug)
            try:
                await asyncio.sleep(self._delay_for(state))
            except asyncio.CancelledError:
                raise

    def snapshot(self) -> dict[str, Any]:
        """The whole panel's state, as served by GET /api/state."""
        return {slug: state.as_dict() for slug, state in self.states.items()}
