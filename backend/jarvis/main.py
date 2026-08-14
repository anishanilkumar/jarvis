"""The dashboard API: one state document, one SSE stream, one action endpoint."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from jarvis import config
from jarvis.cache import Cache
from jarvis.http import build_client
from jarvis.registry import discover
from jarvis.scheduler import Scheduler

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

#: Bounded so a tablet that stops reading (screen off, suspended tab) can't grow
#: a queue until the Pi runs out of memory. Dropping updates is safe: each one
#: carries the provider's full payload, so the next one resyncs the tile.
QUEUE_SIZE = 32

#: Idle keepalive. This is a real named event rather than an SSE comment,
#: because comments do not fire anything in the browser's EventSource — so a
#: comment-based heartbeat cannot tell the panel it is still connected. The
#: panel watchdogs on these; without them a proxy holding a dead socket open
#: leaves the wall showing stale times as though they were live.
HEARTBEAT_SECONDS = 10


class Hub:
    """Fan-out of provider updates to every connected panel."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: str, payload: dict[str, Any]) -> None:
        message = f"event: {event}\ndata: {json.dumps(payload)}\n\n"
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                log.debug("dropping update for a slow subscriber")

    @property
    def count(self) -> int:
        return len(self._subscribers)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = config.load()
    hub = Hub()

    # One shared client: connection reuse matters when departures refresh every
    # 30s, and it keeps us well inside BVG's 100 req/min.
    http = build_client(cfg)

    async def on_update(slug: str) -> None:
        await hub.publish("state", {slug: scheduler.states[slug].as_dict()})

    scheduler = Scheduler(Cache(cfg.state_dir / "cache.json"), on_update)

    for provider_cls in discover():
        scheduler.register(provider_cls(cfg, http), cfg.provider(provider_cls.slug))
    log.info("registered providers: %s", ", ".join(sorted(scheduler.providers)))

    scheduler.start()

    app.state.cfg = cfg
    app.state.hub = hub
    app.state.http = http
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        await scheduler.stop()
        await http.aclose()


app = FastAPI(title="Jarvis dashboard", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    scheduler: Scheduler = request.app.state.scheduler
    return {
        "ok": True,
        "providers": len(scheduler.providers),
        "panels_connected": request.app.state.hub.count,
        "failing": sorted(s.slug for s in scheduler.states.values() if s.error),
    }


@app.get("/api/config")
async def get_config(request: Request) -> dict[str, Any]:
    """The subset of jarvis.toml the panel needs to render and to expire data."""
    cfg = request.app.state.cfg
    scheduler: Scheduler = request.app.state.scheduler
    return {
        "general": cfg.section("general"),
        "location": cfg.section("location"),
        "stop_name": cfg.section("departures").get("stop_name", ""),
        "voice_enabled": bool(cfg.section("voice").get("enabled", False)),
        "useful_for": {slug: st.useful_for for slug, st in scheduler.states.items()},
    }


@app.get("/api/state")
async def get_state(request: Request) -> dict[str, Any]:
    return request.app.state.scheduler.snapshot()


@app.post("/api/action/{slug}")
async def post_action(slug: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Touch writes. Every interactive widget goes through here."""
    scheduler: Scheduler = request.app.state.scheduler
    provider = scheduler.providers.get(slug)
    if provider is None:
        raise HTTPException(404, f"no provider named {slug!r}")
    if not type(provider).supports_action():
        raise HTTPException(405, f"{slug} has no touch actions")

    try:
        result = await provider.action(payload)
    except Exception as exc:  # noqa: BLE001
        log.exception("action on %s failed", slug)
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc

    # Refresh so the write is reflected everywhere, including the panel that
    # didn't perform it, within a second.
    await scheduler.refresh(slug)
    return {"ok": True, "result": result}


@app.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    """SSE. One long-lived connection carrying every provider update.

    Chosen over WebSockets because updates are strictly one-directional and the
    browser's EventSource reconnects by itself after a Wi-Fi drop or a Pi
    restart — behaviour we would otherwise hand-write and get subtly wrong.
    """
    hub: Hub = request.app.state.hub
    scheduler: Scheduler = request.app.state.scheduler
    queue = hub.subscribe()

    async def events() -> AsyncIterator[str]:
        try:
            # Open with the full snapshot so a reconnecting panel is correct
            # immediately, without a separate /api/state round-trip.
            yield f"event: state\ndata: {json.dumps(scheduler.snapshot())}\n\n"
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache, no-transform",
            # Belt and braces alongside Caddy's config: some proxies buffer SSE
            # by default, which makes the stream look alive while delivering
            # nothing.
            "x-accel-buffering": "no",
            "connection": "keep-alive",
        },
    )
