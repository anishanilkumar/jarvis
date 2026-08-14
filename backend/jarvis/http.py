"""The shared outbound HTTP client.

One place, because both the dashboard and the voice service need the same
behaviour, and because getting the address family wrong here is invisible until
one specific upstream starts timing out.
"""

from __future__ import annotations

from typing import Any

import httpx

USER_AGENT = "jarvis (household wall display)"


def build_client(cfg: Any) -> httpx.AsyncClient:
    """An AsyncClient with connection reuse and, by default, IPv4 only.

    `local_address="0.0.0.0"` binds an IPv4 source address, which forces the
    socket family to AF_INET and so skips AAAA results entirely.

    That matters on a host with IPv6 disabled at the kernel: asyncio walks the
    getaddrinfo list in order and will sit on an unreachable IPv6 address until
    the connect timeout, rather than falling back the way curl's Happy Eyeballs
    does. Only upstreams that publish AAAA are affected, which is why it
    presents as one provider failing while the rest are fine.
    """
    transport = None
    if cfg.section("general").get("force_ipv4", True):
        transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=1)

    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        headers={"user-agent": USER_AGENT},
        follow_redirects=True,
        transport=transport,
    )
