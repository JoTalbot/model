"""Tests for optional ``network.outbound_proxy`` parsing."""

import pytest

from swarm.network.outbound_http import (
    httpx_proxy_kwargs,
    outbound_http_proxy_url,
)


def test_proxy_none_when_missing():
    assert outbound_http_proxy_url({}) is None
    assert outbound_http_proxy_url({"network": {}}) is None


def test_proxy_none_when_blank():
    assert outbound_http_proxy_url({"network": {"outbound_proxy": ""}}) is None
    assert outbound_http_proxy_url({"network": {"outbound_proxy": "  "}}) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080",
        "https://proxy.example:8443",
        "socks5://127.0.0.1:9050",
        "socks5h://127.0.0.1:9050",
        "socks4://127.0.0.1:1080",
    ],
)
def test_proxy_accepts_allowed_schemes(url: str):
    assert outbound_http_proxy_url({"network": {"outbound_proxy": url}}) == url


def test_proxy_rejects_unknown_scheme():
    with pytest.raises(ValueError, match=r"network\.outbound_proxy"):
        outbound_http_proxy_url({"network": {"outbound_proxy": "ftp://127.0.0.1:1"}})


def test_httpx_proxy_kwargs_empty():
    assert httpx_proxy_kwargs({}) == {}


def test_httpx_proxy_kwargs_present():
    assert httpx_proxy_kwargs(
        {"network": {"outbound_proxy": "socks5://127.0.0.1:9050"}}
    ) == {"proxy": "socks5://127.0.0.1:9050"}
