"""Last-good values, persisted so a restart doesn't blank the wall.

The panel's most important property is that it never shows an empty tile. When
an upstream API is down, or the service has only just started, the last value we
successfully fetched is better than nothing — provided it is stamped with its
age so nobody mistakes it for live.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class Cache:
    """A slug -> {data, fetched_at} store with an atomic JSON file behind it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._entries = json.loads(self.path.read_text())
            log.info("restored %d cached providers from %s", len(self._entries), self.path)
        except (OSError, json.JSONDecodeError) as exc:
            # A corrupt cache is not worth crashing over; we refetch in seconds.
            log.warning("ignoring unreadable cache %s: %s", self.path, exc)
            self._entries = {}

    def get(self, slug: str) -> dict[str, Any] | None:
        return self._entries.get(slug)

    def put(self, slug: str, data: dict[str, Any], fetched_at: float) -> None:
        self._entries[slug] = {"data": data, "fetched_at": fetched_at}
        self._flush()

    def _flush(self) -> None:
        """Write via a temp file + rename so a power cut can't leave half a file.

        The Pi's SSD write bursts are what caused its historical under-voltage
        dips, so this stays small and infrequent by design — one write per
        successful provider refresh, nothing else.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", dir=self.path.parent, delete=False, suffix=".tmp"
            ) as tmp:
                json.dump(self._entries, tmp)
                tmp_path = Path(tmp.name)
            tmp_path.replace(self.path)
        except OSError as exc:
            log.warning("could not persist cache: %s", exc)
