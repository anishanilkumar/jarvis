"""How stop names, destinations and line names are cleaned up.

Every case here is one a real feed produced. The rules are heuristics over text
from dozens of operators, and each one was written to fix a row that read
badly — which is exactly the kind of rule that quietly breaks another row when
it is changed.
"""

import pytest

from jarvis.providers.departures import _destination
from jarvis.public.geocode import in_germany, ranked, shape_hit
from jarvis.sources.transitous import (
    _german_transit,
    _line_name,
    _on_demand,
    _platform,
    city_of,
    district_of,
    without_city,
)


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("S Wannsee Bhf (Berlin)", "Wannsee"),
        ("S+U Rathaus Steglitz -> 285 Richtung Andrezeile", "Rathaus Steglitz"),
        ("Lindenhof via S Südkreuz", "Lindenhof"),
        ("Zehlendorf, Busseallee", "Zehlendorf"),
        ("Hermannstraße", "Hermannstr."),
        ("Straße des 17. Juni", "Straße des 17. Juni"),
        # Franconia writes "über" as "ü."
        ("Hallstadt ü. Friedhof", "Hallstadt"),
        # Spelled out, as feeds outside Berlin write it
        ("Dietzenbach Bahnhof", "Dietzenbach"),
        ("Hanau Hauptbahnhof", "Hanau Hbf"),
        ("S+U Hauptbahnhof", "Hauptbahnhof"),
        ("Hauptbahnhof", "Hauptbahnhof"),
    ],
)
def test_destination(direction: str, expected: str) -> None:
    assert _destination(direction) == expected


@pytest.mark.parametrize(
    ("name", "city", "expected"),
    [
        ("Fürth Rathaus", "Fürth", "Rathaus"),
        ("Berlin, Brunnenstr./Invalidenstr.", "Berlin", "Brunnenstr./Invalidenstr."),
        ("Köln Niehl Sebastianstr.", "Köln", "Niehl Sebastianstr."),
        # Only when something is left after the town
        ("Wesseling Wesseling", "Wesseling", "Wesseling"),
        ("Bamberg", "Bamberg", "Bamberg"),
        # A street named after the town is not the town
        ("Fürther Str.", "Fürth", "Fürther Str."),
        # OSM's official name carries a qualifier the stops leave out
        ("Heiligenstadt Raiffeisenstr.", "Heiligenstadt i. OFr.", "Raiffeisenstr."),
        ("Heiligenstadt (i.OFr.) Schulen", "Heiligenstadt i. OFr.", "Schulen"),
        ("Heiligenst./OFr Ab. Greifenst.", "Heiligenstadt i. OFr.", "Heiligenst./OFr Ab. Greifenst."),
        ("Marienplatz", "München", "Marienplatz"),
        ("Rathaus", None, "Rathaus"),
    ],
)
def test_without_city(name: str, city: str | None, expected: str) -> None:
    assert without_city(name, city) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("RE19 (4913)", "RE19"),
        ("RB22 (15258)", "RB22"),
        ("ICE 1518", "ICE"),
        ("IC 2024", "IC"),
        ("ECE 5", "ECE"),
        ("S1", "S1"),
        ("M46", "M46"),
        ("X 33", "X 33"),
    ],
)
def test_line_name(name: str, expected: str) -> None:
    assert _line_name(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("221 Rufbus", ("221", True)),
        ("224 AST", ("224", True)),
        ("ALT 12", ("12", True)),
        # Only the marker: keep it, still on demand
        ("AST", ("AST", True)),
        ("221", ("221", False)),
        # Near misses that are ordinary services
        ("Astra 3", ("Astra 3", False)),
        ("BlaBlaCar Bus", ("BlaBlaCar Bus", False)),
    ],
)
def test_on_demand(name: str, expected: tuple[str, bool]) -> None:
    assert _on_demand(name) == expected


def test_platform_that_names_a_mode_is_not_a_platform() -> None:
    # Fürth's feed puts "Bus" where the platform goes; read as one, it would
    # fold both directions of every bus into a single hide.
    assert _platform({"description": "Bus"}) is None
    assert _platform({"description": "U-Bahn"}) is None
    assert _platform({"description": "Gleis 3"}) == "Gleis 3"
    assert _platform({"track": "4"}) == "4"
    assert _platform({}) is None
    # Fürth's U1: the description names the mode, the track is the platform
    assert _platform({"description": "U-Bahn", "track": "2"}) == "2"
    # Bamberg: the description is an island between two tracks; the track is
    # the one this train uses
    assert _platform({"description": "Gleis 6+8", "track": "6"}) == "6"
    # Hamburg: an internal id where the track goes is not a track
    assert _platform({"track": "HHA-U 119004"}) is None


def test_feed_filter() -> None:
    assert _german_transit("de-DELFI_de:09563:2164")
    assert _german_transit("de-VBB_de:11000:900100041::3")
    assert not _german_transit("be-sncb_8015458")
    assert not _german_transit("de-amarillo-bw_de:09162:20")


FUERTH = [
    {"name": "Deutschland", "adminLevel": 2},
    {"name": "Bayern", "adminLevel": 4},
    {"name": "Fürth", "adminLevel": 6},
    {"name": "Süd", "adminLevel": 10},
]
HIRSCHAID = [
    {"name": "Bayern", "adminLevel": 4},
    {"name": "Landkreis Bamberg", "adminLevel": 6},
    {"name": "Hirschaid", "adminLevel": 8},
]
BERLIN = [
    {"name": "Berlin", "adminLevel": 4},
    {"name": "Mitte", "adminLevel": 9},
    {"name": "Moabit", "adminLevel": 10},
]


def test_city_and_district() -> None:
    assert city_of(FUERTH) == "Fürth"
    assert city_of(HIRSCHAID) == "Hirschaid"
    assert city_of(BERLIN) == "Berlin"
    # Outside a city-state the picker shows the town; inside one, the Ortsteil
    assert district_of(FUERTH) == "Fürth"
    assert district_of(HIRSCHAID) == "Hirschaid"
    assert district_of(BERLIN) == "Moabit"


def test_shape_hit_from_bvg_string() -> None:
    hit = {"latitude": 52.53, "longitude": 13.39, "address": "10115 Berlin-Mitte, Invalidenstraße 49"}
    assert shape_hit(hit) == {
        "name": "Invalidenstraße 49", "district": "Mitte", "postcode": "10115",
        "lat": 52.53, "lon": 13.39, "kind": "address",
    }
    # A hyphen outside Berlin is part of the town's name
    hit = {"latitude": 47.5, "longitude": 11.1, "address": "82467 Garmisch-Partenkirchen, Bahnhofstraße 1"}
    assert shape_hit(hit)["district"] == "Garmisch-Partenkirchen"


def test_shape_hit_from_fields() -> None:
    hit = {"latitude": 49.48, "longitude": 10.98, "street": "Königstraße 121",
           "postcode": "90762", "district": "Fürth", "country": "DE"}
    assert shape_hit(hit) == {
        "name": "Königstraße 121", "district": "Fürth", "postcode": "90762",
        "lat": 49.48, "lon": 10.98, "kind": "address",
    }
    assert in_germany(hit)
    assert not in_germany({**hit, "country": "FR"})
    # BVG's answers carry no country and are all Berlin or Brandenburg
    assert in_germany({"address": "10115 Berlin-Mitte, Invalidenstraße 49"})


def test_picker_lists_addresses_first_and_merges_twins() -> None:
    def hit(name: str, kind: str) -> dict:
        return {"name": name, "district": "Heiligenstadt i. OFr.", "postcode": "91332",
                "lat": 49.86, "lon": 11.17, "kind": kind}

    listed = ranked([
        hit("Heiligenstadt Imbiss", "place"),
        hit("Wandern um Heiligenstadt i.OFr.", "place"),
        hit("Marktplatz", "address"),
        hit("Wandern um  Heiligenstadt i.OFr.", "place"),
    ])
    assert [h["name"] for h in listed] == [
        "Marktplatz", "Heiligenstadt Imbiss", "Wandern um Heiligenstadt i.OFr.",
    ]
    assert all("kind" not in h for h in listed)
