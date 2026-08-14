"""Loads jarvis.toml once at startup and exposes it as attribute-ish dicts.

Secrets never live in the TOML — they arrive as environment variables from
agenix-managed files, and are read here so the rest of the code never touches
os.environ directly.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


def _find_config() -> Path:
    """jarvis.toml sits at the repo root, two levels above this package.

    Falls back to jarvis.example.toml so a fresh clone runs before anyone has
    written their own config — the real jarvis.toml is gitignored, since it
    holds a specific home location and hostnames.
    """
    if env := os.environ.get("JARVIS_CONFIG"):
        return Path(env)
    root = Path(__file__).resolve().parents[2]
    real = root / "jarvis.toml"
    return real if real.exists() else root / "jarvis.example.toml"


class Config:
    """Read-only view over jarvis.toml plus the secrets from the environment."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

        # Secrets. Absent is allowed — the provider that needs one degrades to a
        # clear error on its own tile rather than taking the whole panel down.
        self.grocy_api_key = os.environ.get("GROCY_API_KEY", "")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        self.ha_token = os.environ.get("HA_TOKEN", "")

        self.state_dir = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/jarvis"))

    def __getitem__(self, key: str) -> Any:
        return self._raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._raw.get(key, default)

    def section(self, name: str) -> dict[str, Any]:
        """A top-level table, or an empty dict if it isn't in the file."""
        return self._raw.get(name, {})

    def provider(self, slug: str) -> dict[str, Any]:
        """Scheduling policy for one provider: ttl, stale_after, useful_for.

        Defaults are deliberately conservative: a provider whose block someone
        forgot to add refreshes slowly and expires quickly, rather than
        hammering an API or showing day-old data as if it were live.
        """
        block = self._raw.get("providers", {}).get(slug, {})
        return {
            "ttl": block.get("ttl", 300),
            "stale_after": block.get("stale_after", 900),
            "useful_for": block.get("useful_for", 900),
        }

    def provider_enabled(self, slug: str) -> bool:
        """Whether this provider runs at all.

        `enabled = false` is how you take a tile off *this* panel without
        deleting the feature: the provider is never registered, so it never
        polls its upstream, and the widget disappears because the panel renders
        what the Pi actually serves. Turning it back on is one line.
        """
        block = self._raw.get("providers", {}).get(slug, {})
        return bool(block.get("enabled", True))

    @property
    def timezone(self) -> str:
        return self.section("general").get("timezone", "Europe/Berlin")


def load(path: Path | None = None) -> Config:
    path = path or _find_config()
    with path.open("rb") as fh:
        return Config(tomllib.load(fh))
