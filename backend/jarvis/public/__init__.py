"""The public dashboard: the wall's answers, for an address you type in.

Deliberately shares the *shaping* with the wall's providers and none of its
machinery. There is no registry, no scheduler, no cache.json, no SSE and no
voice — a provider is a thing that polls one configured location on a timer,
and this answers arbitrary locations on demand. What it does reuse is every
decision that took a while to get right: how a HAFAS direction string becomes a
destination you would say out loud, how departures fold into route strips, and
which hours a jacket-or-umbrella call is actually about.

It also holds no secrets, which is what makes it safe to put on the open
internet. Open-Meteo and v6.bvg.transport.rest both want no key at all.
"""
