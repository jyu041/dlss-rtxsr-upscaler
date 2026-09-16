import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from src.runtime_manager.core import RuntimeManager, RuntimeSpec, extract_safe_zip, verify_artifact


def spec(**overrides):
    values = {
        "id": "demo", "name": "Demo", "backend": "demo", "version": "1",
        "source": "https://example.invalid/source", "source_url": "https://example.invalid/source",
        "artifact_url": "https://example.invalid/demo.zip", "sha256": None, "size_bytes": None,
        "archive_type": "zip", "allowlist": ("payload.bin",), "destination": "demo", "policy": "UPSTREAM_DOWNLOAD",
    }
    values.update(overrides)
    return RuntimeSpec(**values)


def test_manifest_rejects_non_https_and_unsafe_allowlist():
    with pytest.raises(ValueError, match="HTTPS"):
        RuntimeSpec.from_dict({"id": "x", "name": "x", "backend": "x", "version": "1", "source": "http://x", "source_url": "http://x", "archive_type": "zip", "allowlist": ["x"], "destination": "x", "policy": "UPSTREAM_DOWNLOAD"})
    with pytest.raises(ValueError, match="safe relative"):
        RuntimeSpec.from_dict({**spec(allowlist=("../payload.bin",)).__dict__})


def test_artifact_hash_and_size_are_verified(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"verified")
    digest = hashlib.sha256(b"verified").hexdigest().upper()
    verify_artifact(artifact, spec(sha256=digest, size_bytes=8))
    with pytest.raises(ValueError, match="SHA-256"):
        verify_artifact(artifact, spec(sha256="0" * 64))


def test_safe_zip_rejects_traversal_and_unexpected_members(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.bin", b"bad")
    with pytest.raises(ValueError, match="Unsafe"):
        extract_safe_zip(archive, tmp_path / "stage", ("escape.bin",))
    archive = tmp_path / "unexpected.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("other.bin", b"bad")
    with pytest.raises(ValueError, match="Unexpected"):
        extract_safe_zip(archive, tmp_path / "stage2", ("payload.bin",))


def test_safe_zip_extracts_only_complete_allowlist(tmp_path):
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"ok")
    staging = tmp_path / "stage"
    extract_safe_zip(archive, staging, ("payload.bin",))
    assert (staging / "payload.bin").read_bytes() == b"ok"


def test_manager_manifest_and_state_detection(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"runtimes": [spec().__dict__]}), encoding="utf-8")
    manager = RuntimeManager(manifest, tmp_path / "install")
    loaded, state = manager.inspect("demo")
    assert loaded.version == "1"
    assert state.value == "NOT_INSTALLED"


def test_inventory_labels_user_supplied_components_as_configure(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"runtimes": [spec(policy="USER_SUPPLIED").__dict__]}), encoding="utf-8")
    manager = RuntimeManager(manifest, tmp_path / "install")
    item = manager.inventory()[0]
    assert item["state"] == "NOT_INSTALLED"
    assert item["action"] == "CONFIGURE"


def test_import_and_remove_are_manifest_scoped(tmp_path):
    manifest = tmp_path / "manifest.json"
    demo = spec(allowlist=("payload.bin",), policy="USER_SUPPLIED")
    manifest.write_text(json.dumps({"runtimes": [demo.__dict__]}), encoding="utf-8")
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"ok")
    manager = RuntimeManager(manifest, tmp_path / "install")
    destination = manager.import_zip("demo", archive)
    assert (destination / "payload.bin").read_bytes() == b"ok"
    manager.remove("demo")
    assert not destination.exists()
    assert manager.inspect("demo")[1].value == "NOT_INSTALLED"


def test_activation_runs_selftest_before_recording_state_and_rolls_back(tmp_path):
    manifest = tmp_path / "manifest.json"
    demo = spec(allowlist=("payload.bin",), policy="USER_SUPPLIED")
    manifest.write_text(json.dumps({"runtimes": [demo.__dict__]}), encoding="utf-8")
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"new")
    manager = RuntimeManager(manifest, tmp_path / "install")
    manager.import_zip("demo", archive)
    old = (tmp_path / "install" / "demo" / "payload.bin").read_bytes()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"replacement")
    with pytest.raises(RuntimeError, match="self-test"):
        manager.activate_zip("demo", archive, selftest=lambda _path: (_ for _ in ()).throw(RuntimeError("self-test failed")))
    assert (tmp_path / "install" / "demo" / "payload.bin").read_bytes() == old
    assert manager.inspect("demo")[1].value == "INSTALLED"
