"""Best-effort public client address helper and trusted-proxy config tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from sanic.compat import Header

from oldman.conf.schemas import WebConfig
from oldman.utils.http import FORWARDED_CLIENT_IP_HEADERS, first_public_ip


def request_with(headers: list[tuple[str, str]] | None = None, ip: str | None = "10.0.0.5") -> SimpleNamespace:
    """Build the minimal request shape the helper reads: a Sanic header multi-dict and a peer address."""
    return SimpleNamespace(headers=Header(headers or []), ip=ip)


class FirstPublicIpTest(unittest.TestCase):
    def test_returns_first_globally_routable_hop_and_skips_private_ones(self) -> None:
        request = request_with([("X-Forwarded-For", "10.1.2.3, 192.168.0.9, 8.8.8.8, 1.1.1.1")])

        self.assertEqual("8.8.8.8", first_public_ip(request))

    def test_reserved_ranges_are_not_public(self) -> None:
        # documentation, carrier-grade NAT, link-local and loopback are all non-global
        request = request_with([("X-Forwarded-For", "203.0.113.7, 100.64.0.1, 169.254.1.1, 127.0.0.1")], ip="10.0.0.5")

        self.assertIsNone(first_public_ip(request))

    def test_ipv6_is_supported_and_normalized(self) -> None:
        request = request_with([("X-Forwarded-For", "fe80::1, [2001:4860:4860:0:0:0:0:8888]:443")])

        self.assertEqual("2001:4860:4860::8888", first_public_ip(request))

    def test_ipv4_port_suffix_and_garbage_entries_are_tolerated(self) -> None:
        request = request_with([("X-Forwarded-For", "unknown, not-an-ip, 8.8.4.4:5123")])

        self.assertEqual("8.8.4.4", first_public_ip(request))

    def test_later_headers_are_consulted_when_earlier_ones_have_no_public_entry(self) -> None:
        request = request_with([("X-Forwarded-For", "10.0.0.1"), ("X-Real-IP", "1.0.0.1")])

        self.assertEqual("1.0.0.1", first_public_ip(request))

    def test_repeated_header_lines_are_all_read(self) -> None:
        request = request_with([("X-Forwarded-For", "10.0.0.1"), ("X-Forwarded-For", "9.9.9.9")])

        self.assertEqual("9.9.9.9", first_public_ip(request))

    def test_falls_back_to_peer_only_when_peer_is_public(self) -> None:
        self.assertEqual("8.8.8.8", first_public_ip(request_with(ip="8.8.8.8")))
        self.assertIsNone(first_public_ip(request_with(ip="10.0.0.5")))
        self.assertIsNone(first_public_ip(request_with(ip=None)))

    def test_plain_mapping_headers_and_missing_attributes_are_handled(self) -> None:
        self.assertEqual("8.8.8.8", first_public_ip(SimpleNamespace(headers={"x-forwarded-for": "8.8.8.8"}, ip=None)))
        self.assertIsNone(first_public_ip(SimpleNamespace()))

    def test_header_precedence_keeps_x_forwarded_for_first(self) -> None:
        self.assertEqual("x-forwarded-for", FORWARDED_CLIENT_IP_HEADERS[0])


class WebProxyConfigDefaultsTest(unittest.TestCase):
    def test_trusted_proxy_settings_default_to_disabled(self) -> None:
        config = WebConfig()

        self.assertEqual("X-Real-IP", config.real_ip_header)
        self.assertIsNone(config.proxies_count)
        self.assertIsNone(config.forwarded_secret)

    def test_trusted_proxy_settings_accept_values(self) -> None:
        config = WebConfig(proxies_count=2, forwarded_secret="edge-secret")

        self.assertEqual(2, config.proxies_count)
        self.assertEqual("edge-secret", config.forwarded_secret)


if __name__ == "__main__":
    unittest.main()
