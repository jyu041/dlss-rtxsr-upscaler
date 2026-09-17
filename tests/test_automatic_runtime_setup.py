import json
import zipfile
from pathlib import Path

import pytest

from src.backends import dlss5
from src.runtime_manager import RuntimeManager
from tools import bootstrap_dlss5_runtime as bootstrap


def _write_fake_dlss5_archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in bootstrap.REQUIRED_RUNTIME_FILES:
            archive.writestr(f"DLSS.5.Visual.Enhancer.v3.0/bin/runtime/{name}", name.encode())
        archive.writestr("DLSS.5.Visual.Enhancer.v3.0/bin/runtime/models/model.bin", b"model")
        archive.writestr("DLSS.5.Visual.Enhancer.v3.0/bin/ffmpeg/bin/ffmpeg.exe", b"not-runtime")


def test_dlss5_bootstrap_extracts_only_runtime_tree(tmp_path, monkeypatch):
    archive = tmp_path / "runtime.zip"
    _write_fake_dlss5_archive(archive)
    target = tmp_path / "managed" / "dlss5-v3"
    monkeypatch.setattr(bootstrap, "RUNTIME_TARGET", target)
    result = bootstrap.install_from_archive(archive)
    assert result == target
    assert bootstrap.runtime_complete(target)
    assert (target / "models" / "model.bin").read_bytes() == b"model"
    assert not (target / "ffmpeg.exe").exists()


def test_dlss5_bootstrap_rejects_incomplete_runtime(tmp_path, monkeypatch):
    archive = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("x/bin/runtime/nvngx.dll", b"worker")
    monkeypatch.setattr(bootstrap, "RUNTIME_TARGET", tmp_path / "managed" / "dlss5-v3")
    with pytest.raises(RuntimeError, match="missing required runtime files"):
        bootstrap.install_from_archive(archive)


def test_dlss5_runtime_fingerprint_is_automatic(tmp_path):
    for index, name in enumerate(dlss5.REQUIRED_RUNTIME_FILES.values()):
        (tmp_path / name).write_bytes(f"payload-{index}".encode())
    fingerprint = dlss5.runtime_fingerprint(tmp_path)
    assert set(fingerprint) == set(dlss5.REQUIRED_RUNTIME_FILES)
    assert all(len(value) == 64 for value in fingerprint.values())


def test_validated_legacy_dlssg_runtime_is_direct_upstream_download():
    manager = RuntimeManager(Path("src/runtime_manager/manifest.json"), Path("runtime"))
    spec = manager.specs["dlssg-legacy-reference"]
    assert spec.policy == "UPSTREAM_DOWNLOAD"
    assert spec.channel == "validated"
    assert spec.direct_user_download is True
    assert [item.path for item in spec.files] == ["version.dll", "dlssg_sm86.ini"]
    assert spec.files[0].sha256 == "C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2"


def test_setup_automates_downloadable_backends_and_selftests():
    setup = Path("setup.bat").read_text(encoding="utf-8")
    assert "dlssg-legacy-reference" in setup
    assert "dlssg-official-provider-310.9.1" in setup
    assert "bootstrap_dlss5_runtime.py" in setup
    assert "check_dlss_sr_readiness.py --selftest" in setup
    assert "src.backends.dlss5_selftest" in setup
    assert "approval.json" not in setup


def test_dlss5_backend_has_no_manual_approval_or_firewall_readiness_gate():
    source = Path("src/backends/dlss5.py").read_text(encoding="utf-8")
    assert "approval.json" not in source
    assert "approved_by_user" not in source
    assert "if not self._firewall" not in source
    assert "firewall_advisory" in source
