"""Headlines from an RSS feed.

One headline at a time, rotated by the panel. Not a ticker: a wall display is
read in glances from across a room, and text that is moving while you read it
is text you have to chase. The panel holds each headline still long enough to
finish it and crossfades to the next.

The provider's only job is to hand over a clean, ordered list. How long each
one stays up is a display decision, so `rotate_seconds` rides along with the
data rather than living in the widget.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from jarvis.registry import Provider, Speech

#: Feeds routinely put markup in <title>. Strip it rather than render it.
_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return " ".join(_TAGS.sub("", text).split())


def _published(raw: str | None) -> str | None:
    """RFC-822 as RSS spells it, ISO as the panel wants it."""
    if not raw:
        return None
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.isoformat()


class News(Provider):
    slug = "news"
    intents = [
        "what's in the news",
        "read me the headlines",
        "any news",
        "headlines",
    ]

    async def fetch(self) -> dict[str, Any]:
        conf = self.cfg.section("news")

        response = await self.http.get(conf["feed_url"])
        response.raise_for_status()

        # Parse bytes, not text: the XML declaration carries the encoding, and
        # letting httpx guess from headers gets Malayalam wrong often enough to
        # matter. ElementTree reads the declaration itself.
        root = ET.fromstring(response.content)

        limit = conf.get("headlines", 8)
        headlines: list[dict[str, Any]] = []
        for item in root.findall(".//item"):
            title = _clean(item.findtext("title") or "")
            if not title:
                continue
            headlines.append(
                {
                    "title": title,
                    "link": (item.findtext("link") or "").strip(),
                    "published": _published(item.findtext("pubDate")),
                }
            )
            if len(headlines) >= limit:
                break

        return {
            "source": conf.get("source_name", ""),
            # Seconds each headline holds before the crossfade.
            "rotate_seconds": conf.get("rotate_seconds", 30),
            "headlines": headlines,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        data = await self.fetch()
        headlines = data["headlines"]
        if not headlines:
            return Speech(text="No headlines right now.", focus="news")

        # Three is what a person can hold from a spoken list; the tile is there
        # for the rest.
        spoken = ". ".join(item["title"] for item in headlines[:3])
        return Speech(text=spoken + ".", focus="news")
