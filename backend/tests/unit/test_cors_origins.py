"""Which origins the API answers on.

The terminal is opened from a phone on the home WiFi, so the browser there
sends an Origin the laptop has never seen — a DHCP address that changes. That
rules out an explicit list, and a wildcard is not an option either: browsers
reject "*" alongside allow_credentials. What is left is a pattern, and a
pattern is exactly the kind of thing that silently widens.

So both halves are pinned here: that the private ranges a home network
actually uses are let in, and that nothing outside them is.
"""

from __future__ import annotations

import re

import pytest

from app.core.settings import Settings


@pytest.fixture(scope="module")
def origin_pattern() -> re.Pattern[str]:
    # Starlette matches the header with fullmatch, so anchor the test the
    # same way: a prefix match would accept http://10.0.0.5:3000.evil.com.
    return re.compile(Settings().cors_origin_regex)


def allows(pattern: re.Pattern[str], origin: str) -> bool:
    return pattern.fullmatch(origin) is not None


class TestLanOriginsAreAllowed:
    @pytest.mark.parametrize(
        "origin",
        [
            "http://10.0.0.130:3000",  # this machine, on its home WiFi
            "http://192.168.1.44:3000",
            "http://172.16.5.9:3000",
            "http://172.31.255.1:3000",
            "http://komals-macbook-pro.local:3000",  # Bonjour, when DHCP moves
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
    )
    def test_the_dev_server_reaches_the_api(self, origin_pattern, origin):
        """Port 3000 is the Vite dev server. Without this the phone gets a
        half-loaded terminal rather than an error: the WebSocket is exempt
        from CORS and connects, so live prices arrive while every REST call
        behind them fails."""
        assert allows(origin_pattern, origin)

    @pytest.mark.parametrize(
        "origin",
        ["http://10.0.0.130:4173", "http://192.168.1.44:4173"],
    )
    def test_the_preview_server_reaches_the_api(self, origin_pattern, origin):
        assert allows(origin_pattern, origin)


class TestEverythingElseIsRejected:
    @pytest.mark.parametrize(
        "origin",
        [
            "http://8.8.8.8:3000",  # public address
            "http://172.15.0.1:3000",  # just under the RFC 1918 block
            "http://172.32.0.1:3000",  # just over it
            "http://evil.com:3000",
            "http://10.0.0.130:3000.evil.com",  # suffix, caught by fullmatch
            "http://notlocalhost:3000",
            "https://10.0.0.130:3000",  # scheme is part of the origin
            "http://10.0.0.130:8000",  # the API's own port is not a UI port
            "http://10.0.0.130:5173",  # Vite's default, which this app moved off
        ],
    )
    def test_it_does_not_widen_past_the_home_network(self, origin_pattern, origin):
        assert not allows(origin_pattern, origin)


def test_it_can_be_turned_off_for_a_laptop_only_run():
    """`TRADERAPP_CORS_ORIGIN_REGEX= make backend` is the off switch, so the
    field has to accept an empty value. What the app then does with it is
    tests/integration/test_cors.py."""
    assert Settings(cors_origin_regex="").cors_origin_regex == ""
