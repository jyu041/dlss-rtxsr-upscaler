from pathlib import Path

import src.backends.dlss5_v10_static as v10
from src.backends.dlss5_v10_contract import REQUIRED_EXPORTS


def _write_runtime(root: Path):
    root.mkdir()
    for name in v10.V10_FILES:
        (root / name).write_bytes((name + "-bytes").encode("ascii"))


def _pe(exports=()):
    return {
        "machine": "0x8664",
        "architecture": "x86_64",
        "pe32_plus": True,
        "sections": [],
        "imports": ["KERNEL32.dll"],
        "exports": list(exports),
    }


def test_v10_static_boundary_requires_pinned_hashes(monkeypatch, tmp_path):
    runtime = tmp_path / "v10"
    _write_runtime(runtime)
    monkeypatch.setattr(
        v10,
        "inspect_pe",
        lambda path: _pe(REQUIRED_EXPORTS if path.name == "neuroframe_engine_neural_rendering.dll" else ()),
    )
    status = v10.inspect_v10_runtime(runtime)
    assert status.state == "STATIC_IDENTITY_REQUIRED"
    assert status.valid is False
    assert status.execution_allowed is False


def test_v10_static_boundary_passes_only_with_exact_hashes(monkeypatch, tmp_path):
    runtime = tmp_path / "v10"
    _write_runtime(runtime)
    monkeypatch.setattr(
        v10,
        "inspect_pe",
        lambda path: _pe(REQUIRED_EXPORTS if path.name == "neuroframe_engine_neural_rendering.dll" else ()),
    )
    first = v10.inspect_v10_runtime(runtime)
    expected = {
        name: first.evidence["files"][name]["sha256"]
        for name in v10.V10_FILES
    }
    status = v10.inspect_v10_runtime(runtime, expected_hashes=expected)
    assert status.state == "STATIC_AUDIT_COMPLETE"
    assert status.valid is True
    assert status.execution_allowed is False


def test_v10_static_boundary_rejects_missing_bridge_exports(monkeypatch, tmp_path):
    runtime = tmp_path / "v10"
    _write_runtime(runtime)
    monkeypatch.setattr(v10, "inspect_pe", lambda path: _pe(()))
    status = v10.inspect_v10_runtime(runtime)
    assert status.state == "ABI_MISMATCH"
    assert "dlss5nr_process_frame_v6" in status.evidence["missing_bridge_exports"]


def test_v10_static_boundary_rejects_wrong_architecture(monkeypatch, tmp_path):
    runtime = tmp_path / "v10"
    _write_runtime(runtime)
    def inspect(path):
        report = _pe(REQUIRED_EXPORTS if path.name == "neuroframe_engine_neural_rendering.dll" else ())
        report["architecture"] = "x86"
        return report
    monkeypatch.setattr(v10, "inspect_pe", inspect)
    status = v10.inspect_v10_runtime(runtime)
    assert status.state == "ARCHITECTURE_MISMATCH"
    assert status.execution_allowed is False
