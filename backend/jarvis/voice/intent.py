"""Which widget an utterance is about, decided on the Pi.

This file exists because transcription and routing used to be the same network
call. A cloud model was handed the candidate intents and returned the words and
the route together. Locally there is no such luxury: whisper returns words and
nothing else, so the routing happens here, against the very same catalogue the
providers already declare in their `intents` lists.

The method is deliberately dull — weighted word overlap. No model, no training,
no dependency. What makes it work is that the vocabularies barely intersect:
only `music` says "play", only `rain` says "umbrella", and the one genuinely
close pair, weather and rain, is separated by exactly the words those two
providers chose for themselves. Words that many providers share ("what", "is",
"the") are worth proportionally less, which is TF-IDF in about three lines.

Two consequences worth stating plainly:

- **There is no general-knowledge fallback any more.** The cloud model used to
  answer the long tail — "how tall is the Eiffel Tower" — in the same breath.
  Nothing here can do that, so an utterance that matches no widget is told so
  rather than answered. A wrong answer delivered confidently would be worse.
- **Being wrong is cheap and visible.** A misroute answers a question you did
  not ask, out loud, naming what it did; you hear it and ask again. Silence is
  the failure mode this avoids.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

log = logging.getLogger(__name__)

#: Hyphens kept, so "u-bahn" survives as one discriminative token.
_WORD = re.compile(r"[a-z0-9-]+")

#: Words that carry no routing signal. Kept short on purpose: every word struck
#: off here is a word the weighting would have discounted anyway, and a long
#: stoplist is a good way to accidentally delete the one word that mattered.
#:
#: "we" and "need" earned their place back the hard way. Both look like filler,
#: and striking them out meant `shopping`'s "we need" phrasing consisted of
#: nothing at all — so "we need bread" routed nowhere. They are ordinary words
#: that happen to be how people ask for something, and the weighting below
#: already discounts them for being shared.
_STOP = frozenset("""
a an and any are as at be but by can could do does for from get give go going
have how i if in is it its like me my of on or should so take tell that
the their them then there they this to us was what whats when where which
who will with would you your
""".split())

#: A single word used by exactly one provider scores 1.0. Requiring that much
#: means a route is never chosen on shared filler alone — "what is the" matches
#: everything and therefore nothing.
MIN_SCORE = 0.9


def tokens(text: str) -> list[str]:
    """Lowercase content words. Apostrophes are dropped rather than split, so
    "what's" becomes "whats" and lands in the stoplist like "what" does."""
    stripped = text.lower().replace("'", "").replace("’", "")
    return [word for word in _WORD.findall(stripped) if word and word not in _STOP]


def _signal(example: str) -> list[str]:
    """The routable words of one declared phrasing.

    A provider's example must never reduce to nothing. If every word in it is
    filler, the filler *is* the phrasing — that is the whole of how someone
    asks — and dropping it silently deletes a phrase the provider advertises as
    speakable. Falling back to the raw words keeps the catalogue honest: what a
    provider declares is what voice will match.
    """
    return tokens(example) or _WORD.findall(example.lower().replace("'", ""))


class IntentMatcher:
    """Built once at startup from the providers' declared example phrasings."""

    def __init__(self, catalogue: dict[str, list[str]]) -> None:
        self.vocabulary: dict[str, set[str]] = {
            slug: {token for example in examples for token in _signal(example)}
            for slug, examples in catalogue.items()
        }

        # How many providers claim each word. A word claimed by one is worth a
        # whole point; a word claimed by four is worth a quarter.
        spread: Counter[str] = Counter()
        for vocab in self.vocabulary.values():
            spread.update(vocab)
        self.weight = {token: 1.0 / count for token, count in spread.items()}

    def scores(self, transcript: str) -> list[tuple[str, float]]:
        """Every provider, best first. Useful in the log when a route surprises you."""
        heard = set(tokens(transcript))
        ranked = [
            (slug, sum(self.weight[token] for token in heard & vocab))
            for slug, vocab in self.vocabulary.items()
        ]
        return sorted(ranked, key=lambda pair: pair[1], reverse=True)

    def match(self, transcript: str) -> str | None:
        """The provider this utterance belongs to, or None for "no idea"."""
        ranked = self.scores(transcript)
        if not ranked:
            return None

        slug, score = ranked[0]
        if score < MIN_SCORE:
            log.info("no intent for %r (best %s at %.2f)", transcript, slug, score)
            return None

        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        log.info("intent %s at %.2f (next %.2f) for %r", slug, score, runner_up, transcript)
        return slug


# --- Slots ------------------------------------------------------------------
#
# Only the four the providers actually read. Each pattern is anchored on the
# phrasing the provider itself advertises, so what is extractable stays tied to
# what is speakable — the same principle as the catalogue above.

_ITEM = re.compile(
    r"\b(?:add|put)\s+(?P<item>.+?)\s+(?:to|on)\s+(?:the\s+)?(?:shopping\s+)?list\b"
    r"|\bwe\s+need\s+(?P<need>.+?)\s*$",
    re.IGNORECASE,
)
_QUERY = re.compile(r"\b(?:play|put\s+on)\s+(?P<query>.+?)\s*$", re.IGNORECASE)
_LINE = re.compile(r"\b(?:tram|bus|line|u-?bahn|s-?bahn)\s+(?P<line>[a-z]?\d+[a-z]?)\b", re.IGNORECASE)
#: Digits only. Whisper writes "2" for "two" often enough to be useful and not
#: reliably enough to promise, so a missed amount means the provider's own
#: default applies rather than a wrong number being asserted.
_AMOUNT = re.compile(r"\b(?P<amount>\d+)\b")


def slots_for(intent: str | None, transcript: str) -> dict[str, Any]:
    """Pull the arguments this intent knows how to use out of the words."""
    found: dict[str, Any] = {}

    if intent == "shopping":
        if match := _ITEM.search(transcript):
            item = (match.group("item") or match.group("need") or "").strip(" .,")
            if item:
                found["item"] = item
        if match := _AMOUNT.search(transcript):
            found["amount"] = int(match.group("amount"))

    elif intent == "music":
        if match := _QUERY.search(transcript):
            # "play some music" is a request for anything, not for a track
            # called "some music" — leave the slot empty and let the provider
            # ask, which is what it already does for a bare "play".
            query = match.group("query").strip(" .,")
            if query.lower() not in {"some music", "music", "something", "anything"}:
                found["query"] = query

    elif intent == "departures":
        if match := _LINE.search(transcript):
            found["line"] = match.group("line").upper()

    return found
