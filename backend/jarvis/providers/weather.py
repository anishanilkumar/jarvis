"""Weather and rain from Open-Meteo — free, no key, open DWD/ECMWF model data.

Two providers rather than one because they age at completely different rates: an
hours-old temperature is still worth showing, an hours-old "rain in 20 minutes"
is worthless. Separate providers means separate `useful_for` in jarvis.toml, so
each expires on its own terms.
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
    slug = "rain"
    intents = [
        "will it rain",
        "is it going to rain",
        "do I need an umbrella",
        "should I take a jacket",
    ]

    async def fetch(self) -> dict[str, Any]:
        wx = self.cfg.section("weather")
        buckets = wx.get("rain_buckets", 8)
        threshold = wx.get("rain_likely_threshold", 40)

        raw = await self._get(
            minutely_15="precipitation,precipitation_probability",
            hourly="precipitation_probability",
            forecast_minutely_15=buckets,
            forecast_days=1,
        )
        minutely = raw["minutely_15"]

        series = [
            {
                "time": minutely["time"][i],
                "probability": minutely["precipitation_probability"][i] or 0,
                "mm": minutely["precipitation"][i] or 0.0,
            }
            for i in range(len(minutely["time"]))
        ]

        # The headline is the whole point of this tile: not a chart to study,
        # one sentence answering "do I need a jacket right now".
        first_wet = next((p for p in series if p["probability"] >= threshold), None)
        if first_wet is None:
            headline, expected = "Dry for the next two hours", False
        else:
            when = datetime.fromisoformat(first_wet["time"])
            soonest = series[0]["time"] == first_wet["time"]
            headline = (
                "Rain right about now"
                if soonest
                else f"Rain likely around {when.strftime('%-H:%M')}"
            )
            expected = True

        return {
            "headline": headline,
            "rain_expected": expected,
            "threshold": threshold,
            "series": series,
            "peak": max((p["probability"] for p in series), default=0),
        }

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        data = await self.fetch()
        if not data["rain_expected"]:
            return Speech(text="No rain expected in the next two hours.", focus="rain")
        return Speech(text=f"{data['headline']}, peaking at {data['peak']} percent.", focus="rain")
