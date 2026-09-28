"""Authenticate callers by the network they call from, a named entry of ``web.auth.ip_allowlist``."""

from __future__ import annotations

import ipaddress
from typing import Any

import oldman.conf as conf
from oldman.web.authentication.base import Authentication
from oldman.web.request import client_ip

IP_ALLOWLIST_METHOD = "ip_allowlist"


def _address(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """An address as Sanic reports it, plain or IPv6 in brackets; a socket path or a proxy's obfuscated name is None."""
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    # A server listening on "::" sees an IPv4 caller as ::ffff:a.b.c.d.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


class IPAllowlistAuthentication:
    """A request whose addresses fall in one entry of ``web.auth.ip_allowlist``.

    Two addresses are checked, and both must be in the same entry: the socket peer
    (``request.ip``) and the client address (``request.client_ip``, which Sanic takes from the
    proxy headers ``web.real_ip_header``, ``proxies_count`` and ``forwarded_secret`` describe).
    Any client can send those headers, and Sanic believes them whoever sent them; requiring the
    peer too means a forged header admits no one who could not already connect from the list.
    Behind a proxy the entry therefore lists the proxy's address beside the clients', and the peer is
    always the proxy: then a forged header is kept out only if the proxy overwrites
    ``real_ip_header`` (or only appends to ``X-Forwarded-For`` under ``proxies_count``) instead of
    passing on what the client sent. That is a deployment precondition this code cannot check (G1-9).

    The caller is not a user: ``request.ctx.user`` stays anonymous and ``request.ctx.auth.caller``
    is the entry's name. A browser on an allowed network sends its address with every request,
    so the credential is ambient and CSRF protection applies. Listed before another method, a
    signed-in user on an allowed network would be taken for the network, so
    ``resolve_authenticators`` requires this one to come last.
    """

    name = IP_ALLOWLIST_METHOD

    def __init__(self) -> None:
        entries = conf.settings.web.auth.ip_allowlist
        if not entries:
            raise ValueError("web.auth.authenticators lists 'ip_allowlist' but web.auth.ip_allowlist is empty")
        self._entries = tuple((caller, tuple(ipaddress.ip_network(network) for network in networks)) for caller, networks in entries.items())

    async def authenticate(self, request: Any) -> Authentication | None:
        peer = _address(str(getattr(request, "ip", None) or ""))
        client = _address(client_ip(request))
        if peer is None or client is None:
            return None
        for caller, networks in self._entries:
            if any(peer in network for network in networks) and any(client in network for network in networks):
                return Authentication(method=self.name, caller=caller, ambient=True)
        return None


__all__ = ["IP_ALLOWLIST_METHOD", "IPAllowlistAuthentication"]
