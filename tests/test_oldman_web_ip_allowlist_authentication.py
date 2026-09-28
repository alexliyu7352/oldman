"""IP allowlist: callers recognized by the network they call from, never by a forwarded address alone."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from pydantic import ValidationError
from sanic import Sanic
from sanic.response import json

import oldman.conf as conf
from oldman.conf.schemas import AuthConfig, DefaultSettings
from oldman.web.auth import authenticated_by
from oldman.web.authentication import (
    Authentication,
    IPAllowlistAuthentication,
    exempt_from_csrf,
    install_authentication,
    resolve_authenticators,
)
from oldman.web.session import SessionData

LOCAL = ["127.0.0.1/32", "::1/128"]


def allowlist_settings(entries: dict[str, list[str]]) -> DefaultSettings:
    settings = DefaultSettings()
    settings.web.auth = AuthConfig.model_validate({"ip_allowlist": entries})
    return settings


class IPAllowlistTestCase(unittest.TestCase):
    def use(self, entries: dict[str, list[str]]) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": allowlist_settings(entries)}))

    def serve(self) -> Sanic:
        """A Sanic app that believes X-Real-IP, as a service does with the default web.real_ip_header."""
        app = Sanic(f"ip_allowlist_{self._testMethodName}")
        self.addCleanup(lambda: Sanic.unregister_app(app))
        app.config.REAL_IP_HEADER = "X-Real-IP"
        install_authentication(app, (IPAllowlistAuthentication(),))

        async def endpoint(request: Any) -> Any:
            return json({"caller": request.ctx.auth.caller, "user": request.ctx.user.id})

        guard: Any = authenticated_by("ip_allowlist")
        app.add_route(guard(endpoint), "/internal", name="internal")
        return app

    def recognize(self, ip: str, forwarded: str = "") -> Authentication | None:
        """What the method makes of a request from ``ip``, which a proxy header says came from ``forwarded``."""
        request = SimpleNamespace(ip=ip, client_ip=forwarded or ip, headers={})
        return asyncio.run(IPAllowlistAuthentication().authenticate(request))


class IPAllowlistAuthenticationTest(IPAllowlistTestCase):
    def test_a_request_from_a_listed_network_is_that_caller(self) -> None:
        self.use({"local": LOCAL})

        _, response = self.serve().test_client.get("/internal")

        self.assertEqual((200, {"caller": "local", "user": None}), (response.status, response.json))

    def test_behind_a_proxy_the_entry_lists_the_proxy_beside_the_clients(self) -> None:
        self.use({"local": LOCAL, "office": ["10.0.0.0/8", "127.0.0.1"]})
        app = self.serve()

        _, office = app.test_client.get("/internal", headers={"X-Real-IP": "10.1.2.3"})
        _, outside = app.test_client.get("/internal", headers={"X-Real-IP": "203.0.113.9"})

        self.assertEqual((200, "office"), (office.status, office.json["caller"]))
        self.assertEqual(401, outside.status)

    def test_a_forwarded_address_alone_admits_no_one(self) -> None:
        """Sanic believes X-Real-IP from any peer; one not on the list cannot claim an address that is."""
        self.use({"office": ["10.0.0.0/8"]})

        _, forged = self.serve().test_client.get("/internal", headers={"X-Real-IP": "10.1.2.3"})

        self.assertEqual(401, forged.status)
        self.assertIsNone(self.recognize("203.0.113.9", forwarded="10.1.2.3"))

    def test_addresses_are_read_in_every_form_sanic_reports(self) -> None:
        self.use({"local": LOCAL})

        self.assertEqual("local", getattr(self.recognize("::ffff:127.0.0.1"), "caller", None))  # dual-stack listener
        self.assertEqual("local", getattr(self.recognize("::1", forwarded="[::1]"), "caller", None))  # bracketed by Sanic
        for peer, forwarded in (("127.0.0.1", "_hidden"), ("", ""), ("127.0.0.1", "127.0.0.1:8080")):
            with self.subTest(peer=peer, forwarded=forwarded):
                self.assertIsNone(self.recognize(peer, forwarded))

    def test_an_allowed_network_is_ambient_so_csrf_still_applies(self) -> None:
        request = SimpleNamespace(
            ctx=SimpleNamespace(session=SessionData(), auth=Authentication(method="ip_allowlist", caller="local", ambient=True))
        )

        self.assertFalse(exempt_from_csrf(request))


class IPAllowlistConfigurationTest(unittest.TestCase):
    def test_listing_ip_allowlist_without_networks_is_refused_at_startup(self) -> None:
        with patch.dict(conf.__dict__, {"settings": DefaultSettings()}), self.assertRaises(ValueError):
            resolve_authenticators(["ip_allowlist"], session_enabled=False)

    def test_ip_allowlist_must_come_last(self) -> None:
        with patch.dict(conf.__dict__, {"settings": allowlist_settings({"local": LOCAL})}):
            with self.assertRaisesRegex(ValueError, "last"):
                resolve_authenticators(["ip_allowlist", "session"], session_enabled=True)

            methods = resolve_authenticators(["session", "ip_allowlist"], session_enabled=True)

        self.assertEqual(["session", "ip_allowlist"], [method.name for method in methods])

    def test_each_entry_lists_networks_without_host_bits(self) -> None:
        for entries in ({"empty": []}, {"typo": ["10.0.0.300"]}, {"widened": ["10.0.0.1/8"]}):
            with self.subTest(entries=entries), self.assertRaises(ValidationError):
                AuthConfig.model_validate({"ip_allowlist": entries})


if __name__ == "__main__":
    unittest.main()
