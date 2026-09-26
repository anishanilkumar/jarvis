"""Which stops get a board, and which routes end up on which board."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from jarvis.public import nearby
from jarvis.sources.transitous import lookahead


def route(line: str, destination: str, product: str, **extra: Any) -> dict[str, Any]:
    return {"line": line, "destination": destination, "product": product,
            "departures": [], **extra}


def board(name: str, walk: int, *routes: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "walk_minutes": walk, "routes": list(routes), "warnings": []}


def lines(boards: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {b["name"]: [r["line"] for r in b["routes"]] for b in boards}


def test_route_kept_when_its_nearest_stop_loses_its_slot() -> None:
    """Elisabethkirchstr., September 2026: the M8's nearest stop was a tram-only
    board that lost its slot to the U- and S-Bahn, and the M8 vanished though
    U Rosenthaler Platz, which kept its slot, runs it too."""
    shaped = [
        board("Brunnenstr./Invalidenstr.", 3,
              route("M8", "Hauptbahnhof", "tram"),
              route("12", "Pasedagplatz", "bus")),
        board("U Rosenthaler Platz", 7,
              route("U8", "Hermannstr.", "subway"),
              route("M8", "Hauptbahnhof", "tram"),
              route("M1", "Rosenthal", "tram")),
        board("S Nordbahnhof", 8,
              route("S1", "Wannsee", "suburban"),
              route("M10", "Warschauer Str.", "tram")),
    ]
    composed = nearby.compose_boards(shaped, {}, limit=3)
    assert lines(composed) == {
        "U Rosenthaler Platz": ["U8", "M8", "M1"],
        "S Nordbahnhof": ["S1", "M10"],
        "Buses": ["12"],
    }


def test_route_stays_at_nearest_stop_when_it_fits() -> None:
    shaped = [
        board("Near", 2, route("M8", "Hauptbahnhof", "tram")),
        board("Far", 6, route("U8", "Wittenau", "subway"), route("M8", "Hauptbahnhof", "tram")),
    ]
    composed = nearby.compose_boards(shaped, {}, limit=3)
    assert lines(composed) == {"Far": ["U8"], "Near": ["M8"]}


def test_on_demand_runs_are_a_route_of_their_own() -> None:
    """The regular 236 and its booked-only runs must not fold into one row, at
    one stop or across two."""
    shaped = [
        board("Ortsmitte", 2,
              route("236", "Ebermannstadt", "bus"),
              route("236", "Ebermannstadt", "bus", on_demand=True)),
        board("Wiesengrundstr.", 7, route("236", "Ebermannstadt", "bus", on_demand=True)),
    ]
    composed = nearby.compose_boards(shaped, {}, limit=3)
    pooled = composed[-1]
    assert [(r["line"], bool(r.get("on_demand"))) for r in pooled["routes"]] == [
        ("236", False), ("236", True),
    ]


def test_choose_stops_prefers_a_new_mode() -> None:
    """Three bus stops nearer than the S-Bahn must not take all three slots."""
    stops = [
        {"id": "1", "name": "Bus A", "distance": 100, "products": {"bus": True}},
        {"id": "2", "name": "Bus B", "distance": 150, "products": {"bus": True}},
        {"id": "3", "name": "Bus C", "distance": 200, "products": {"bus": True}},
        {"id": "4", "name": "S Station", "distance": 600, "products": {"suburban": True}},
    ]
    chosen = nearby.choose_stops(stops, 2)
    assert [s["name"] for s in chosen] == ["Bus A", "S Station"]


def test_far_station_joins_when_no_rail_is_near(monkeypatch: Any) -> None:
    """A village with only buses inside the radius gets its station, with
    only its trains."""
    calls: list[int] = []

    async def attempt(operation: str, *, radius: int, **_: Any) -> tuple[str, list[dict[str, Any]]]:
        calls.append(radius)
        village = [{"id": "v1", "name": "Ortsmitte", "distance": 150, "products": {"bus": True}}]
        if radius <= 900:
            return "transitous", village
        if radius <= 2500:
            return "transitous", village  # still no train
        return "transitous", village + [
            {"id": "s1", "name": "Ebermannstadt", "distance": 3100,
             "products": {"regional": True, "bus": True}},
        ]

    monkeypatch.setattr(nearby.sources, "attempt", attempt)
    name, stops = asyncio.run(nearby.stops_near(
        None, {}, 49.8, 11.1, count=5, radius=900, rail_radii=(2500, 6000),
    ))
    assert calls == [900, 2500, 6000]
    assert [s["name"] for s in stops] == ["Ortsmitte", "Ebermannstadt"]
    assert stops[1]["only_products"] == ["regional"]
    assert nearby.board_for(stops[1], metres_per_minute=80)["products"] == ["regional"]


def test_no_wider_search_when_rail_is_near(monkeypatch: Any) -> None:
    calls: list[int] = []

    async def attempt(operation: str, *, radius: int, **_: Any) -> tuple[str, list[dict[str, Any]]]:
        calls.append(radius)
        return "transitous", [{"id": "u", "name": "U Rathaus", "distance": 60,
                               "products": {"subway": True}}]

    monkeypatch.setattr(nearby.sources, "attempt", attempt)
    asyncio.run(nearby.stops_near(None, {}, 49.4, 11.0, count=5, radius=900,
                                  rail_radii=(2500, 6000)))
    assert calls == [900]


def departure(minutes: int) -> dict[str, Any]:
    at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    return {"when": at, "plannedWhen": at, "line": {"name": "230"}}


def test_lookahead_only_when_asked() -> None:
    later = [departure(m) for m in (120, 300, 3000, 4000)]
    assert lookahead(later, {}, {}) == []
    kept = lookahead(later, {}, {"lookahead_hours": 60, "lookahead_results": 2})
    assert kept == later[:2]
    # Beyond the horizon is dropped
    assert len(lookahead(later, {}, {"lookahead_hours": 10, "lookahead_results": 9})) == 2
