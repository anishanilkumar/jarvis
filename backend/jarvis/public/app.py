"""The public dashboard's API.

Stateless by construction. Every answer is a function of the coordinates in the
query string, which is what lets the whole thing be a cache in front of two
free upstreams and nothing else. There is no session, no database, no disk and
no key; a restart costs one cold minute and loses nothing.

The one design decision worth reading twice is where the jacket threshold is
applied. It is not applied here. `/api/weather` returns the forecast *facts* —
the coldest hour you have left today and the wettest — and the browser turns
those into "take a jacket" using the visitor's own preference. That falls out
of the caching: the response is keyed on rounded coordinates and shared by
everyone standing near that rounding, so it cannot carry one person's opinion
about what counts as cold. The payoff is that moving the slider re-decides
instantly, with no network at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Request

from jarvis import config as config_module
from jarvis.http import build_client
from jarvis.providers.weather import (
    ADVICE_CURRENT,
    ADVICE_HOURLY,
    WEATHER_CURRENT,
    WEATHER_DAILY,
    advice_facts,
    shape_weather,
)
from jarvis import sources
from jarvis.public import geocode, nearby
from jarvis.public.cache import TTLCache, round_coords
from jarvis.public.limits import Bbox, RateLimiter, caller

SWEEP_SECONDS = 300

#: The public config, two levels above this package. Named explicitly rather
#: than leaning on config.load()'s own search, which falls back to the wall's
#: jarvis.toml — a fallback that would let this service come up on the Pi with
#: the household's own coordinates and no [public] block, looking fine.
DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "jarvis-public.toml"


def _config_path() -> Path:
    if env := os.environ.get("JARVIS_CONFIG"):
        return Path(env)
    return DEFAULT_CONFIG


class Service:
    """Everything the request handlers need, built once at startup."""

    def __init__(self) -> None:
        self.cfg = config_module.load(_config_path())
        pub = self.cfg.section("public")

        self.wx = self.cfg.section("weather")
        self.dep = self.cfg.section("departures")
        self.timezone = self.cfg.timezone

        self.bbox = Bbox(pub.get("bbox", {}))
        self.stop_count = pub.get("nearby_stops", 3)
        # Deliberately more stops than boards. Which stops deserve one depends
        # on the routes they actually run, and that is only knowable after
        # fetching them; the surplus costs a few upstream calls per cache miss
        # and buys the difference between a third board that repeats the first
        # and a third board with the U-Bahn on it.
        self.stop_candidates = pub.get("nearby_candidates", self.stop_count + 2)
        self.stop_radius = pub.get("nearby_radius_m", 900)
        self.metres_per_minute = float(pub.get("walk_metres_per_minute", 80))
        self.limiter = RateLimiter(pub.get("rate_limit_per_minute", 60))
        self.upstream = asyncio.Semaphore(pub.get("max_concurrent_upstream", 8))

        self.geocode_cache = TTLCache(pub.get("cache_geocode_seconds", 3600))
        self.weather_cache = TTLCache(pub.get("cache_weather_seconds", 600))
        self.departures_cache = TTLCache(pub.get("cache_departures_seconds", 30))

        self.http: httpx.AsyncClient = build_client(self.cfg)

    @property
    def weather_api(self) -> str:
        return self.wx.get("api_base", "https://api.open-meteo.com/v1/forecast")

    def caches(self) -> tuple[TTLCache, ...]:
        return (self.geocode_cache, self.weather_cache, self.departures_cache)


service: Service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service
    service = Service()

    async def sweeper() -> None:
        while True:
            await asyncio.sleep(SWEEP_SECONDS)
            for cache in service.caches():
                cache.sweep()
            service.limiter.sweep()

    task = asyncio.create_task(sweeper())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await service.http.aclose()


app = FastAPI(title="jarvis public dashboard", lifespan=lifespan)


def _gate(request: Request) -> None:
    if not service.limiter.allow(caller(request)):
        raise HTTPException(status_code=429, detail="Slow down a moment.")


def _in_berlin(lat: float, lon: float) -> None:
    """Refuse coordinates outside the city.

    Enforced here rather than only in the address picker: the URL parameters
    accept lat/lon directly — that is the point of them — so the picker is a
    courtesy and this is the rule. Without it the service is a free worldwide
    proxy for two APIs that are somebody else's to pay for.
    """
    if not service.bbox.contains(lat, lon):
        raise HTTPException(
            status_code=400,
            detail="That location is outside Berlin. This dashboard only covers Berlin for now.",
        )


async def _upstream(coro: Any) -> Any:
    """One upstream call, under the global concurrency cap.

    A failed upstream becomes a 502 with the reason rather than a traceback: the
    page distinguishes "the dashboard is down" from "BVG is down" and can only
    do that if the difference survives the wire.
    """
    try:
        async with service.upstream:
            return await coro
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Upstream answered {exc.response.status_code}."
        ) from exc
    except httpx.HTTPError as exc:
        # str() on a ConnectError is frequently empty, which produced the
        # message "Upstream unreachable: " — the colon promising a reason that
        # never came. The class name is at least a real answer.
        reason = str(exc) or type(exc).__name__
        raise HTTPException(status_code=502, detail=f"Upstream unreachable: {reason}") from exc


async def _cached(cache: TTLCache, key: Any, produce: Any) -> Any:
    """Fresh if the upstreams are answering, last-good with its age if not.

    The age is stamped into the body rather than dropped, because the browser
    computes every countdown and every freeze from when it believes the data
    was fetched. Handing it a twenty-minute-old board with no note would restart
    countdowns that should already have frozen — the exact dishonesty the
    freezing rule exists to prevent, reintroduced by the cache that was supposed
    to help.
    """
    value, age = await cache.get(key, produce, stale_ok=True)
    if age and isinstance(value, dict):
        return {**value, "stale_seconds": int(age)}
    return value


@app.get("/api/health")
async def health() -> dict[str, Any]:
    # Reports which upstreams are currently being tried, so a degraded service
    # is visible from outside without reading the journal. Still "ok" while a
    # source is tripped: that is the fallback working, not the service failing.
    return {"ok": True, "city": "Berlin", "sources": sources.health()}


@app.get("/api/geocode")
async def geocode_endpoint(
    request: Request, q: str = Query(min_length=2, max_length=120)
) -> dict[str, Any]:
    _gate(request)
    key = " ".join(q.split()).casefold()

    async def produce() -> list[dict[str, Any]]:
        _, hits = await _upstream(geocode.search(service.http, service.dep, q))
        found = []
        for hit in hits:
            if not geocode.looks_berlin(hit):
                continue
            shaped = geocode.shape_hit(hit)
            if shaped and service.bbox.contains(shaped["lat"], shaped["lon"]):
                found.append(shaped)
        return found

    # Served stale without comment, and only here: a street's coordinates do
    # not move, so an hour-old geocode is not stale in any sense the reader
    # cares about. Worth having at all because the picker going down with the
    # board is what turns an outage into "this site does not work".
    results, _ = await service.geocode_cache.get(key, produce, stale_ok=True)
    return {"results": results}


@app.get("/api/weather")
async def weather_endpoint(
    request: Request, lat: float, lon: float
) -> dict[str, Any]:
    _gate(request)
    _in_berlin(lat, lon)
    rounded = round_coords(lat, lon)

    async def produce() -> dict[str, Any]:
        params = {
            "latitude": rounded[0],
            "longitude": rounded[1],
            # Fixed rather than "auto" so the rounded pair fully determines the
            # cache key — Berlin is one timezone and this is a Berlin-only page.
            "timezone": service.timezone,
        }

        async def fetch(**extra: Any) -> dict[str, Any]:
            response = await service.http.get(
                service.weather_api, params={**params, **extra}
            )
            response.raise_for_status()
            return response.json()

        conditions, advice = await asyncio.gather(
            _upstream(
                fetch(
                    current=WEATHER_CURRENT,
                    daily=WEATHER_DAILY,
                    forecast_days=service.wx.get("forecast_days", 7),
                )
            ),
            _upstream(
                fetch(current=ADVICE_CURRENT, hourly=ADVICE_HOURLY, forecast_days=2)
            ),
        )

        return {
            "weather": shape_weather(conditions),
            "advice": advice_facts(
                advice, min_hours=service.wx.get("advice_min_hours", 6)
            ),
            # Defaults the page starts from. The browser owns the decision, so
            # these travel as data rather than being applied here.
            "jacket_below": service.wx.get("jacket_below", 14),
            "rain_threshold": service.wx.get("rain_likely_threshold", 40),
        }

    return await _cached(service.weather_cache, rounded, produce)


@app.get("/api/departures")
async def departures_endpoint(
    request: Request,
    lat: float,
    lon: float,
    # Tokens an earlier response issued, each naming a stop or a direction the
    # visitor has hidden. Opaque to the page; nearby.apply_hides reads them.
    hide: list[str] = Query(default=[]),
) -> dict[str, Any]:
    _gate(request)
    _in_berlin(lat, lon)
    rounded = round_coords(lat, lon)

    async def produce() -> dict[str, Any]:
        found_by, stops = await _upstream(
            nearby.stops_near(
                service.http,
                service.dep,
                rounded[0],
                rounded[1],
                count=service.stop_candidates,
                radius=service.stop_radius,
            )
        )
        if not stops:
            # Not an error. Berlin has addresses with no stop inside 900m, and
            # a page that says so is more useful than one that says "failed".
            return {"shaped": [], "warnings": [], "sources": []}

        return await _upstream(
            nearby.fetch_boards(
                service.http,
                stops,
                service.dep,
                metres_per_minute=service.metres_per_minute,
                # Pinned: these ids came from one source and mean nothing to
                # the other.
                found_by=found_by,
            )
        )

    # The cache holds every nearby stop's board and is shared by everyone near
    # this rounding. Hides are one visitor's, so they are applied after it, per
    # request — which keeps a hide from costing an upstream call, and keeps the
    # cache from splitting into one entry per visitor's taste.
    fetched = await _cached(service.departures_cache, rounded, produce)
    return nearby.compose_view(fetched, service.dep, hide, limit=service.stop_count)
