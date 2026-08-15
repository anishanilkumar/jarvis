"""Headlines from an RSS feed.

One story at a time — headline, one-line excerpt, and the story's picture —
rotated by the panel. Not a ticker: a wall display is read in glances from
across a room, and text that is moving while you read it is text you have to
chase. The panel holds each story still long enough to finish it and crossfades
to the next.

The provider's only job is to hand over a clean, ordered list. How long each
one stays up is a display decision, so `rotate_seconds` rides along with the
data rather than living in the widget.

Excerpt and image are both best-effort. Feeds disagree about where either
lives — some carry a media:thumbnail, some bury an <img> in the HTML body, and
rbb24 carries no picture at all — so both are optional all the way through to
the CSS, and a story with neither still renders as a headline.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from jarvis.registry import Provider, Speech

#: Feeds routinely put markup in <title>, and always in <description>.
_TAGS = re.compile(r"<[^>]+>")
#: The fallback image source: the first <img> in the story body.
_IMG_SRC = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)

#: Namespaces carrying the two things plain RSS has no element for.
_MEDIA = "{http://search.yahoo.com/mrss/}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


def _clean(text: str) -> str:
    """Entity-decode first, then strip tags.

    That order matters for the feeds that escape their HTML twice: ElementTree
    hands back `&lt;p&gt;` where the file said `&amp;lt;p&amp;gt;`, and a tag
    stripper run before the unescape would leave the literal angle brackets on
    the wall.
    """
    return " ".join(_TAGS.sub("", html.unescape(text)).split())


def _excerpt(item: ET.Element, title: str, limit: int) -> str:
    """The standfirst under the headline, trimmed to fit the tile.

    Truncation is at a word boundary — a wall panel clamps the line visually
    anyway, so the only job here is to stop shipping an entire article body for
    the feeds whose <description> is the whole story.
    """
    text = _clean(item.findtext("description") or "")
    # Some feeds set description to the headline again. Repeating the title in
    # smaller grey type underneath it is worse than showing nothing.
    if not text or text.casefold() == title.casefold():
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.—–-")
    return f"{cut}…"


def _image(item: ET.Element) -> str:
    """The story picture, wherever this particular feed decided to put it."""
    thumbnail = item.find(f"{_MEDIA}thumbnail")
    if thumbnail is not None and thumbnail.get("url"):
        return thumbnail.get("url", "")

    for media in item.findall(f"{_MEDIA}content"):
        kind = media.get("type", "")
        if media.get("url") and (media.get("medium") == "image" or kind.startswith("image/")):
            return media.get("url", "")

    for enclosure in item.findall("enclosure"):
        if enclosure.get("url") and enclosure.get("type", "").startswith("image/"):
            return enclosure.get("url", "")

    # Last resort: the first <img> in the body. Feeds that ship full HTML often
    # carry no image metadata at all, and the lead image is usually first.
    body = (item.findtext(f"{_CONTENT}encoded") or "") + (item.findtext("description") or "")
    found = _IMG_SRC.search(html.unescape(body))
    return found.group(1) if found else ""


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
        excerpt_chars = conf.get("excerpt_chars", 220)
        headlines: list[dict[str, Any]] = []
        for item in root.findall(".//item"):
            title = _clean(item.findtext("title") or "")
            if not title:
                continue
            headlines.append(
                {
                    "title": title,
                    "excerpt": _excerpt(item, title, excerpt_chars),
                    # Empty string, not null, when the feed has no picture: the
                    # panel treats it as "text only" and lays out accordingly.
                    "image": _image(item),
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
