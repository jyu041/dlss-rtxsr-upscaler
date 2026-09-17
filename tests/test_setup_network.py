import os
import subprocess
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
    assert setup.index("HTTP_PROXY") < setup.index("where conda")
    assert setup.index("HTTP_PROXY") < setup.index("conda env update")


@pytest.mark.skipif(os.name != "nt", reason="setup.bat validation is Windows-only")
def test_setup_batch_rejects_discard_proxy_without_reaching_conda():
    env = os.environ.copy()
    env["HTTP_PROXY"] = "http://127.0.0.1:9"
    env["HTTPS_PROXY"] = "http://127.0.0.1:9"
    env["ALL_PROXY"] = "http://127.0.0.1:9"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "setup.bat"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 2, output
    assert "NETWORK BLOCKED" in output
    assert "Run setup.bat from a normal network-enabled terminal" in output
    assert "[2/10] Creating/updating Python environment" not in output


def test_setup_supports_exact_archive_fallback_and_managed_cache():
    setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    assert "tools\\check_setup_network.py --require-download" in setup
    assert "NVE_DLSS5_ARCHIVE" in setup
    assert "tools\\provision_dlss5_v3.py --yes --archive" in setup
    assert "tools\\cache_dlss5_v3_archive.py" in setup
    assert "runtime\\cache\\dlss5-v3\\DLSS.5.Visual.Enhancer.v3.0.zip" in setup
