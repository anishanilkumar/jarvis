"""Meal plan and shopping list, read from the Grocy instance on the VPS.

Grocy already holds the recipes, the meal plan and the stock, so these tiles are
a view onto data that exists rather than a second place to maintain it. The
shopping list is also the panel's write path: it is what "add rice to the
shopping list" reaches, and the pattern every future interactive widget copies.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from jarvis.registry import Provider, Speech

log = logging.getLogger(__name__)


class _Grocy(Provider):
    """Shared Grocy request plumbing."""

    async def _get(self, path: str, **params: Any) -> Any:
        conf = self.cfg.section("grocy")
        if not self.cfg.grocy_api_key:
            raise RuntimeError("GROCY_API_KEY is not set")
        response = await self.http.get(
            f"{conf['api_base'].rstrip('/')}/{path.lstrip('/')}",
            params=params or None,
            headers={"GROCY-API-KEY": self.cfg.grocy_api_key},
        )
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        conf = self.cfg.section("grocy")
        if not self.cfg.grocy_api_key:
            raise RuntimeError("GROCY_API_KEY is not set")
        response = await self.http.post(
            f"{conf['api_base'].rstrip('/')}/{path.lstrip('/')}",
            json=body,
            headers={"GROCY-API-KEY": self.cfg.grocy_api_key},
        )
        response.raise_for_status()
        return response.json() if response.content else {}

    async def _products(self) -> list[dict[str, Any]]:
        return await self._get("objects/products")


class Meals(_Grocy):
    slug = "meals"
    intents = [
        "what's for dinner",
        "what are we eating",
        "what's the meal plan",
        "what's cooking",
    ]

    async def fetch(self) -> dict[str, Any]:
        conf = self.cfg.section("grocy")
        span = conf.get("meal_plan_days", 2)
        wanted = {(date.today() + timedelta(days=i)).isoformat() for i in range(span)}

        plan = await self._get("objects/meal_plan")
        recipes = {int(r["id"]): r for r in await self._get("objects/recipes")}

        entries: list[dict[str, Any]] = []
        for item in plan:
            day = (item.get("day") or "")[:10]
            if day not in wanted:
                continue

            entry: dict[str, Any] = {
                "day": day,
                "is_today": day == date.today().isoformat(),
                "kind": item.get("type") or "recipe",
                "title": (item.get("note") or "").strip(),
                "servings": item.get("recipe_servings"),
                "missing": None,
                "recipe_id": None,
            }

            recipe = recipes.get(int(item["recipe_id"])) if item.get("recipe_id") else None
            if recipe:
                entry["title"] = recipe.get("name") or entry["title"]
                entry["recipe_id"] = int(recipe["id"])
                entry["description"] = _strip_html(recipe.get("description") or "")
                # "What am I missing?" is the reason to show a meal plan on a
                # kitchen wall at all. A failure here shouldn't lose the meal.
                try:
                    fulfillment = await self._get(f"recipes/{recipe['id']}/fulfillment")
                    entry["missing"] = int(fulfillment.get("missing_products_count") or 0)
                except Exception as exc:  # noqa: BLE001
                    log.debug("fulfillment unavailable for recipe %s: %s", recipe["id"], exc)

            if entry["title"]:
                entries.append(entry)

        entries.sort(key=lambda e: e["day"])
        return {"entries": entries, "today": date.today().isoformat()}

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        data = await self.fetch()
        today = [e for e in data["entries"] if e["is_today"]]
        if not today:
            return Speech(text="Nothing is planned for today.", focus="meals")

        titles = ", ".join(e["title"] for e in today)
        missing = sum(e["missing"] or 0 for e in today)
        text = f"Today: {titles}."
        if missing:
            text += f" You're missing {missing} ingredient{'s' if missing != 1 else ''}."
        return Speech(text=text, focus="meals")


class Shopping(_Grocy):
    slug = "shopping"
    intents = [
        "add to the shopping list",
        "put it on the shopping list",
        "we need",
        "what's on the shopping list",
    ]

    async def fetch(self) -> dict[str, Any]:
        conf = self.cfg.section("grocy")
        list_id = int(conf.get("shopping_list_id", 1))

        items = await self._get("objects/shopping_list")
        products = {int(p["id"]): p["name"] for p in await self._products()}

        entries = [
            {
                "id": int(item["id"]),
                # Grocy items are either a product reference or a free-text
                # note. Voice-added items are often the latter, when what was
                # said doesn't match anything in the product catalogue.
                "name": products.get(int(item["product_id"]))
                if item.get("product_id")
                else (item.get("note") or "").strip(),
                "amount": _tidy_amount(item.get("amount")),
                "done": bool(int(item.get("done") or 0)),
            }
            for item in items
            if int(item.get("shopping_list_id") or 1) == list_id
        ]
        entries = [e for e in entries if e["name"]]

        return {
            "items": entries,
            "outstanding": sum(1 for e in entries if not e["done"]),
        }

    async def action(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """add {name, amount} | toggle {id, done}.

        Touch and voice both land here, so there is exactly one code path that
        writes to the list.
        """
        conf = self.cfg.section("grocy")
        list_id = int(conf.get("shopping_list_id", 1))
        op = payload.get("op", "add")

        if op == "toggle":
            item_id = int(payload["id"])
            done = 1 if payload.get("done") else 0
            await self._post(f"objects/shopping_list/{item_id}", {"done": done})
            return {"id": item_id, "done": bool(done)}

        if op == "add":
            name = (payload.get("name") or "").strip()
            if not name:
                raise ValueError("nothing to add")
            amount = float(payload.get("amount") or 1)

            product_id = await self._match_product(name)
            body: dict[str, Any] = {"shopping_list_id": list_id, "amount": amount}
            if product_id is not None:
                body["product_id"] = product_id
            else:
                # No catalogue match: keep it as free text rather than refusing.
                # A shopping list that rejects "the good bread" is useless.
                body["note"] = name
            await self._post("objects/shopping_list", body)
            return {"added": name, "matched_product": product_id is not None}

        raise ValueError(f"unknown op {op!r}")

    async def _match_product(self, name: str) -> int | None:
        """Case-insensitive exact match first, then a containment fallback."""
        needle = name.casefold()
        products = await self._products()
        for product in products:
            if (product.get("name") or "").casefold() == needle:
                return int(product["id"])
        for product in products:
            haystack = (product.get("name") or "").casefold()
            if needle in haystack or haystack in needle:
                return int(product["id"])
        return None

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        item = (slots.get("item") or "").strip()
        if not item:
            data = await self.fetch()
            pending = [e["name"] for e in data["items"] if not e["done"]]
            if not pending:
                return Speech(text="The shopping list is empty.", focus="shopping")
            return Speech(
                text=f"{len(pending)} things: " + ", ".join(pending[:6]) + ".",
                focus="shopping",
            )

        await self.action({"op": "add", "name": item, "amount": slots.get("amount") or 1})
        # Speaker ID is used here to attribute, never to authorise.
        who = f", {speaker}" if speaker else ""
        return Speech(text=f"Added {item} to the shopping list{who}.", focus="shopping")


def _strip_html(text: str) -> str:
    """Grocy stores recipe descriptions as HTML; the panel renders plain text."""
    import re

    return re.sub(r"<[^>]+>", " ", text).replace("&nbsp;", " ").strip()


def _tidy_amount(value: Any) -> float | int | None:
    """Grocy returns amounts as strings like '2.0'. Show 2, not 2.0."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 2)
