import pytest

from tools import check_setup_network as network


def test_discard_proxy_is_rejected(monkeypatch):
    monkeypatch.setattr(
        network.urllib.request,
        "getproxies",
        lambda: {"https": "http://127.0.0.1:9"},
    )
    assert network.blocked_discard_proxies() == {"https": "http://127.0.0.1:9"}
    with pytest.raises(RuntimeError, match="local discard proxy"):
        network.require_download_network_context()


def test_legitimate_local_proxy_is_not_rejected(monkeypatch):
    monkeypatch.setattr(
        network.urllib.request,
        "getproxies",
        lambda: {"https": "http://127.0.0.1:7890"},
    )
    assert network.blocked_discard_proxies() == {}
    network.require_download_network_context()


def test_direct_network_context_is_allowed(monkeypatch):
    monkeypatch.setattr(network.urllib.request, "getproxies", lambda: {})
    assert network.blocked_discard_proxies() == {}
    network.require_download_network_context()
