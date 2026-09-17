from pathlib import Path

import pytest

from tools import check_setup_network as network


ROOT = Path(__file__).parents[1]


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


def test_environment_does_not_fall_back_to_anaconda_defaults():
    environment = (ROOT / "environment.yml").read_text(encoding="utf-8")
    assert "  - conda-forge\n" in environment
    assert "  - nodefaults\n" in environment
    assert "repo.anaconda.com" not in environment


def test_setup_fails_fast_on_discard_proxy_before_conda_update():
    setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    assert "HTTP_PROXY" in setup
    assert "HTTPS_PROXY" in setup
    assert "ALL_PROXY" in setup
    assert "127.0.0.1" in setup
    assert "local discard proxy" in setup
    assert setup.index("HTTP_PROXY") < setup.index("conda env update")


def test_setup_supports_exact_archive_fallback():
    setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    assert "tools\\check_setup_network.py --require-download" in setup
    assert "NVE_DLSS5_ARCHIVE" in setup
    assert "tools\\provision_dlss5_v3.py --yes --archive" in setup
