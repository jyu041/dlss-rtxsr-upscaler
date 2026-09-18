import hashlib
from pathlib import Path
import zipfile

import pytest

from src.runtime_manager.core import RuntimeSpec
from tools.audit_runtime_candidate import audit_static_archive


def _static_spec(archive: Path, *, static_only: bool = True) -> RuntimeSpec:
    return RuntimeSpec(
        id="static-demo",
        name="Static Demo",
        backend="demo",
        version="1",
        source="https://example.invalid/project",
        source_url="https://example.invalid/project/commit/abc",
        artifact_url="https://example.invalid/demo.zip",
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest().upper(),
        size_bytes=archive.stat().st_size,
        archive_type="selective-zip",
        allowlist=("bin/runtime.bin",),
        destination="demo/static",
        policy="UPSTREAM_DOWNLOAD",
        constraints={"static_only": static_only},
        channel="candidate-static-only",
        redistributable=False,
        direct_user_download=True,
    )


def test_static_audit_records_exact_selected_file_identity_without_execution(tmp_path):
    archive = tmp_path / "candidate.zip"
    payload = b"candidate-runtime-bytes"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("bin/runtime.bin", payload)
        handle.writestr("docs/readme.txt", b"ignored")

    report = audit_static_archive(_static_spec(archive), archive)

    assert report["static_only"] is True
    assert report["executed"] is False
    assert report["archive"]["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest().upper()
    assert report["files"] == [{
        "path": "bin/runtime.bin",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
    }]


def test_static_audit_refuses_non_static_runtime(tmp_path):
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("bin/runtime.bin", b"x")

    with pytest.raises(ValueError, match="not marked static_only"):
        audit_static_archive(_static_spec(archive, static_only=False), archive)


def test_static_audit_rejects_archive_identity_mismatch(tmp_path):
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("bin/runtime.bin", b"x")

    spec = _static_spec(archive)
    archive.write_bytes(archive.read_bytes() + b"tamper")

    with pytest.raises(ValueError, match="Artifact size mismatch|Artifact SHA-256 mismatch"):
        audit_static_archive(spec, archive)
