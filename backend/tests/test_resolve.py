"""The wall's address and stop names, turned into coordinates and ids."""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from jarvis import resolve, sources
from jarvis.config import Config
from jarvis.sources import bvg

FUERTH_AREAS = [{"name": "Bayern", "adminLevel": 4}, {"name": "Fürth", "adminLevel": 6}]


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def config(tmp_path: Path, raw: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> tuple[Config, dict[str, Any]]:
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    return Config(raw), raw


@pytest.fixture(autouse=True)
def fresh_breakers() -> None:
    sources._breakers.clear()


def test_fuerth_wall_resolves_through_transitous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside Berlin and Brandenburg BVG is never asked for a stop, and the
    board gets a Transitous id and no BVG one."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(f"{request.url.host}{request.url.path}")
        if request.url.host == "api.transitous.org" and request.url.params.get("type") == "STOP":
            return httpx.Response(200, json=[
                # Same name, 190 km away: must not be taken
                {"type": "STOP", "id": "de-DELFI_de:09162:1", "name": "Rathaus",
                 "lat": 48.13, "lon": 11.57, "areas": []},
                {"type": "STOP", "id": "de-DELFI_de:09563:2164", "name": "Fürth Rathaus",
                 "lat": 49.4775, "lon": 10.9895, "areas": FUERTH_AREAS},
            ])
        if request.url.host == "api.transitous.org":
            return httpx.Response(200, json=[
                {"type": "ADDRESS", "name": "Königstraße 121", "street": "Königstraße",
                 "houseNumber": "121", "zip": "90762", "country": "DE",
                 "lat": 49.4748, "lon": 10.9923, "areas": FUERTH_AREAS},
            ])
        return httpx.Response(500)

    cfg, raw = config(tmp_path, {
        "location": {"address": "Königstraße 121, Fürth"},
        "departures": {"boards": [{"stop": "Rathaus"}]},
    }, monkeypatch)

    async def run() -> None:
        async with client(handler) as http:
            await resolve.apply(cfg, http)

    asyncio.run(run())
    assert raw["location"]["name"] == "Fürth"
    board = raw["departures"]["boards"][0]
    assert board["transitous_stop_id"] == "de-DELFI_de:09563:2164"
    assert "stop_id" not in board
    assert board["name"] == "Rathaus"
    assert board["walk_minutes"] == 5
    assert not any("bvg" in url for url in asked)
    remembered = json.loads((tmp_path / "resolved.json").read_text())
    assert "stop:Rathaus" in remembered


def test_berlin_stop_while_bvg_is_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "bvg" in request.url.host:
            return httpx.Response(503)
        return httpx.Response(200, json=[
            {"type": "STOP", "id": "de-VBB_de:11000:900100023", "name": "U Rosenthaler Platz (Berlin)",
             "lat": 52.5298, "lon": 13.4014, "areas": [{"name": "Berlin", "adminLevel": 4}]},
        ])

    cfg, raw = config(tmp_path, {
        "location": {"latitude": 52.5335, "longitude": 13.3974},
        "departures": {"boards": [{"stop": "U Rosenthaler Platz"}]},
    }, monkeypatch)

    async def run() -> None:
        async with client(handler) as http:
            await resolve.apply(cfg, http)

    asyncio.run(run())
    board = raw["departures"]["boards"][0]
    assert board["transitous_stop_id"] == "de-VBB_de:11000:900100023"
    assert board["stop_name"] == "U Rosenthaler Platz"


def test_bvg_skips_a_transitous_board_without_tripping() -> None:
    """One wall board resolved outside BVG must not open BVG's breaker for the
    others."""
    async def run() -> None:
        with pytest.raises(sources.NotHere):
            await bvg.departures(None, board={"transitous_stop_id": "de-DELFI_x"}, conf={})

    asyncio.run(run())

    calls: list[str] = []

    async def fake_bvg(**_: Any) -> Any:
        calls.append("bvg")
        raise sources.NotHere("x")

    async def fake_transitous(**_: Any) -> Any:
        calls.append("transitous")
        return {"departures": []}

    class Bvg:
        NAME = "bvg"
        departures = staticmethod(fake_bvg)

    class Transitous:
        NAME = "transitous"
        departures = staticmethod(fake_transitous)

    original = sources.SOURCES
    sources.SOURCES = (Bvg, Transitous)
    try:
        for _ in range(5):
            name, _ = asyncio.run(sources.attempt("departures", board={}))
            assert name == "transitous"
    finally:
        sources.SOURCES = original
    assert sources.breaker("bvg").opened_at is None
    assert sources.breaker("bvg").failures == 0


def test_unresolvable_name_refuses_to_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    cfg, _ = config(tmp_path, {
        "location": {"latitude": 49.47, "longitude": 10.99},
        "departures": {"boards": [{"stop": "Nowhere"}]},
    }, monkeypatch)

    async def run() -> None:
        async with client(handler) as http:
            await resolve.apply(cfg, http)

    with pytest.raises(resolve.Unresolved):
        asyncio.run(run())
