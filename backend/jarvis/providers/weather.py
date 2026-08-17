"""Weather from Open-Meteo — free, no key, open DWD/ECMWF model data.

Two providers rather than one because they answer different questions. `Weather`
reports conditions: what it is doing outside and what it will do this week.
`Rain` reports a decision: whether to pick up a jacket, an umbrella, both or
neither on the way out. Splitting them also splits `useful_for` in jarvis.toml —
an hours-old temperature is still worth reading, an hours-old recommendation
about the hours you have already spent outdoors is not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from jarvis.registry import Provider, Speech

#: WMO weather interpretation codes, collapsed to the distinctions that are
#: actually visible on a wall tile. Fine-grained codes (light vs moderate
#: drizzle) get one label and one icon; nobody reads that difference at 2m.
WMO: dict[int, tuple[str, str]] = {
    0: ("Clear", "clear"),
    1: ("Mostly clear", "clear"),
    2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"),
    48: ("Freezing fog", "fog"),
    51: ("Drizzle", "drizzle"),
    53: ("Drizzle", "drizzle"),
    55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "sleet"),
    57: ("Freezing drizzle", "sleet"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "sleet"),
    67: ("Freezing rain", "sleet"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Showers", "showers"),
    81: ("Showers", "showers"),
    82: ("Heavy showers", "showers"),
    85: ("Snow showers", "snow"),
    86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm", "storm"),
    99: ("Thunderstorm", "storm"),
}


def describe(code: int | None) -> dict[str, str]:
    label, icon = WMO.get(code or 0, ("Unknown", "unknown"))
    return {"label": label, "icon": icon}


class _OpenMeteo(Provider):
    """Shared request plumbing for both weather tiles."""

    async def _get(self, **params: Any) -> dict[str, Any]:
        loc = self.cfg.section("location")
        wx = self.cfg.section("weather")
        response = await self.http.get(
            wx.get("api_base", "https://api.open-meteo.com/v1/forecast"),
            params={
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "timezone": self.cfg.timezone,
                **params,
            },
        )
        response.raise_for_status()
        return response.json()


class Weather(_OpenMeteo):
    slug = "weather"
    intents = [
        "what's the weather",
        "how cold is it",
        "how warm is it",
        "what's the forecast",
        "when is sunset",
    ]

    async def fetch(self) -> dict[str, Any]:
        days = self.cfg.section("weather").get("forecast_days", 7)
        raw = await self._get(
            current="temperature_2m,apparent_temperature,weather_code,is_day,"
            "wind_speed_10m,relative_humidity_2m",
            daily="temperature_2m_max,temperature_2m_min,weather_code,"
            "precipitation_probability_max,sunrise,sunset",
            forecast_days=days,
        )
        current, daily = raw["current"], raw["daily"]

        return {
            "temperature": round(current["temperature_2m"]),
            "apparent": round(current["apparent_temperature"]),
            "humidity": current.get("relative_humidity_2m"),
            "wind": round(current.get("wind_speed_10m") or 0),
            "is_day": bool(current.get("is_day")),
            "condition": describe(current.get("weather_code")),
            "today": {
                "high": round(daily["temperature_2m_max"][0]),
                "low": round(daily["temperature_2m_min"][0]),
                "sunrise": daily["sunrise"][0],
                "sunset": daily["sunset"][0],
            },
            "forecast": [
                {
                    "date": daily["time"][i],
                    "high": round(daily["temperature_2m_max"][i]),
                    "low": round(daily["temperature_2m_min"][i]),
                    "rain_chance": daily["precipitation_probability_max"][i],
                    "condition": describe(daily["weather_code"][i]),
                }
                for i in range(len(daily["time"]))
            ],
        }

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        data = await self.fetch()
        if "sunset" in utterance.lower():
            when = datetime.fromisoformat(data["today"]["sunset"])
            return Speech(text=f"Sunset is at {when.strftime('%-I:%M %p').lstrip('0')}.", focus="weather")
        return Speech(
            text=(
                f"{data['condition']['label']}, {data['temperature']} degrees, "
                f"feels like {data['apparent']}. "
                f"High of {data['today']['high']} today."
            ),
            focus="weather",
        )


class Rain(_OpenMeteo):
    """What to take with you, rather than what the sky is going to do.

    A probability strip made you do the arithmetic yourself — read eight bars,
    decide what they mean, then decide what to carry. This answers the last
    question directly and only that: jacket, umbrella, both, or neither.

    Both answers are drawn from the hours you have left in the day, not from
    the whole calendar day: at six in the evening the shower that fell at
    breakfast is not a reason to pick up an umbrella. Late at night that
    remainder shrinks to nothing useful, so the window has a floor and spills
    into tomorrow — a jacket decided at 23:00 is a decision about the morning.
    """

    slug = "rain"
    intents = [
        "will it rain",
        "is it going to rain",
        "do I need an umbrella",
        "should I take a jacket",
        # "what should I take" would be the obvious phrasing and is deliberately
        # not here: every word in it is a stopword, so the matcher reduces it to
        # nothing and it can never route. "wear" is the one word in that
        # neighbourhood no other provider claims.
        "what should I wear",
    ]

    async def fetch(self) -> dict[str, Any]:
        wx = self.cfg.section("weather")
        threshold = wx.get("rain_likely_threshold", 40)
        jacket_below = wx.get("jacket_below", 14)
        min_hours = wx.get("advice_min_hours", 6)

        raw = await self._get(
            current="apparent_temperature",
            hourly="apparent_temperature,precipitation_probability",
            forecast_days=2,
        )
        hourly = raw["hourly"]

        # Open-Meteo is asked for local time, so `current.time` is a clock
        # reading in the household's own timezone — which saves carrying a
        # tzdata lookup around just to know what "today" means here.
        now = datetime.fromisoformat(raw["current"]["time"])
        this_hour = now.replace(minute=0, second=0, microsecond=0)

        rows = [
            {
                "time": hourly["time"][i],
                "apparent": hourly["apparent_temperature"][i],
                "probability": hourly["precipitation_probability"][i] or 0,
            }
            for i in range(len(hourly["time"]))
            if datetime.fromisoformat(hourly["time"][i]) >= this_hour
        ]
        rest_of_today = [
            r for r in rows if datetime.fromisoformat(r["time"]).date() == now.date()
        ]
        window = rest_of_today if len(rest_of_today) >= min_hours else rows[:min_hours]

        # Apparent temperature already folds in wind chill and humidity, which
        # is exactly the number a jacket is a response to. Raw air temperature
        # would let a cold, hard wind off the Panke read as a mild afternoon.
        #
        # A null temperature is dropped rather than defaulted: a gap in the
        # model output is not evidence of a mild hour, and coercing it to zero
        # would recommend a jacket on a missing reading.
        warm = [r for r in window if r["apparent"] is not None]
        coldest = min(warm, key=lambda r: r["apparent"]) if warm else None
        wettest = max(window, key=lambda r: r["probability"]) if window else None

        jacket = coldest is not None and coldest["apparent"] <= jacket_below
        umbrella = wettest is not None and wettest["probability"] >= threshold

        spans_tomorrow = bool(window) and (
            datetime.fromisoformat(window[-1]["time"]).date() != now.date()
        )

        return {
            "jacket": {
                "needed": jacket,
                "apparent": round(coldest["apparent"]) if coldest else None,
                "at": coldest["time"] if coldest else None,
                "below": jacket_below,
            },
            "umbrella": {
                "needed": umbrella,
                "probability": wettest["probability"] if wettest else 0,
                "at": wettest["time"] if wettest else None,
                "threshold": threshold,
            },
            "headline": _headline(jacket, umbrella),
            "through": window[-1]["time"] if window else None,
            "spans_tomorrow": spans_tomorrow,
        }

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        data = await self.fetch()
        jacket, umbrella = data["jacket"], data["umbrella"]
        spoken = utterance.lower()

        # Asked about one of the two specifically, answer only that one — the
        # question was "do I need an umbrella", not "brief me on the weather".
        if "umbrella" in spoken or "rain" in spoken:
            if not umbrella["needed"]:
                return Speech(
                    text=f"No umbrella needed. Rain peaks at {umbrella['probability']} percent.",
                    focus="rain",
                )
            return Speech(
                text=(
                    f"Take an umbrella. Rain reaches {umbrella['probability']} percent "
                    f"around {_clock(umbrella['at'])}."
                ),
                focus="rain",
            )
        if "jacket" in spoken:
            if not jacket["needed"]:
                return Speech(
                    text=f"No jacket needed. It stays around {jacket['apparent']} degrees.",
                    focus="rain",
                )
            return Speech(
                text=(
                    f"Take a jacket. It feels like {jacket['apparent']} degrees "
                    f"by {_clock(jacket['at'])}."
                ),
                focus="rain",
            )

        return Speech(text=f"{data['headline']}.", focus="rain")


def _clock(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%-H:%M") if iso else "later"


def _headline(jacket: bool, umbrella: bool) -> str:
    if jacket and umbrella:
        return "Take a jacket and an umbrella"
    if jacket:
        return "Take a jacket"
    if umbrella:
        return "Take an umbrella"
    return "Nothing to take"
