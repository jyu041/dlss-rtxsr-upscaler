from pathlib import Path

import pytest

import tools.validate_dlssg_instrumented as instrumented


def test_instrumented_worker_gate_rejects_outside_directory(monkeypatch, tmp_path):
    root = tmp_path / "instrumented"
    root.mkdir()
    worker = tmp_path / "elsewhere.exe"
    worker.write_bytes(b"worker")
    monkeypatch.setattr(instrumented, "INSTRUMENTED_ROOT", root.resolve())
    with pytest.raises(RuntimeError, match="must be under"):
        instrumented.require_instrumented_worker(worker)


def test_instrumented_worker_gate_rejects_production_hash(monkeypatch, tmp_path):
    root = tmp_path / "instrumented"
    root.mkdir()
    worker = root / "dlssg_sm86_offline.exe"
    worker.write_bytes(b"worker")
    monkeypatch.setattr(instrumented, "INSTRUMENTED_ROOT", root.resolve())
    monkeypatch.setattr(
        instrumented,
        "sha256_file",
        lambda path: instrumented.C55_WORKER_SHA256,
    )
    with pytest.raises(RuntimeError, match="refuses the pinned production C55 binary"):
        instrumented.require_instrumented_worker(worker)


def test_instrumented_worker_gate_accepts_distinct_build(monkeypatch, tmp_path):
    root = tmp_path / "instrumented"
    root.mkdir()
    worker = root / "dlssg_sm86_offline.exe"
    worker.write_bytes(b"worker")
    monkeypatch.setattr(instrumented, "INSTRUMENTED_ROOT", root.resolve())
    monkeypatch.setattr(instrumented, "sha256_file", lambda path: "A" * 64)
    assert instrumented.require_instrumented_worker(worker) == "A" * 64


def test_runtime_identity_gate_requires_both_pinned_hashes(monkeypatch, tmp_path):
    runtime = tmp_path / "version.dll"
    official = tmp_path / "official"
    official.mkdir()
    provider = official / "nvngx_dlssg.dll"
    runtime.write_bytes(b"legacy")
    provider.write_bytes(b"provider")

    hashes = {
        runtime.resolve(): instrumented.LEGACY_RUNTIME_SHA256,
        provider.resolve(): instrumented.OFFICIAL_PROVIDER_SHA256,
    }
    monkeypatch.setattr(
        instrumented,
        "sha256_file",
        lambda path: hashes[path.resolve()],
    )
    identity = instrumented.require_runtime_identity(runtime, official)
    assert identity == {
        "community_runtime_sha256": instrumented.LEGACY_RUNTIME_SHA256,
        "official_provider_sha256": instrumented.OFFICIAL_PROVIDER_SHA256,
    }


def test_instrumented_validator_matrices_are_bounded_in_source():
    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "validate_dlssg_instrumented.py"
    ).read_text(encoding="utf-8")
    assert '"bounded": {' in source
    assert '"practical": {' in source
    assert '"geometries": ((256, 256),)' in source
    assert '"geometries": ((1280, 720), (1920, 1080))' in source
    assert '"multipliers": (2, 3, 4)' in source
    assert '"multipliers": (2, 4)' in source
    assert 'cells.append(("external", 1, default_grid))' in source
    assert 'cells.append((f"nvof-grid{grid}", 2, grid))' in source
    assert '"nvof_only": True' in source
    assert '"validation_geometries"' in source
