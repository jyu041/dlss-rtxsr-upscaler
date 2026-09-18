from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.prepare_dlss5_v10_candidate as prep


class _Manager:
    def __init__(self, *args, **kwargs):
        self.specs = {
            prep.RUNTIME_ID: SimpleNamespace(
                allowlist=(
                    "bin/runtime/dlssnr/nvngx_dlssnr.dll",
                    "bin/runtime/dlssnr/neuroframe_engine_neural_rendering.dll",
                    "bin/runtime/dlssnr/neuroframe_caller.dll",
                    "bin/runtime/dlssnr/LICENSE-NVIDIA-DLSS.txt",
                    "bin/runtime/dlssnr/LICENSE-Merserk.txt",
                ),
                sha256="A" * 64,
            )
        }


def _fake_extract(_archive, staged, allowlist, selective):
    assert selective is True
    for member in allowlist:
        path = staged / member
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(member.encode("utf-8"))


def _gate(hashes):
    return {
        "state": "STATIC_AUDIT_COMPLETE",
        "valid": True,
        "execution_allowed": False,
        "evidence": {
            "files": {
                name: {"sha256": value}
                for name, value in hashes.items()
            }
        },
    }


def test_v10_research_stage_is_atomic_and_nonexecuting(monkeypatch, tmp_path):
    archive = tmp_path / "v10.zip"
    archive.write_bytes(b"archive")
    destination = tmp_path / "runtime" / "candidate"
    report = tmp_path / "audit" / "report.json"

    hashes = {
        "nvngx_dlssnr.dll": "1" * 64,
        "neuroframe_engine_neural_rendering.dll": "2" * 64,
        "neuroframe_caller.dll": "3" * 64,
    }

    monkeypatch.setattr(prep, "RuntimeManager", _Manager)
    monkeypatch.setattr(prep, "verify_artifact", lambda archive, spec: None)
    monkeypatch.setattr(prep, "extract_safe_zip", _fake_extract)
    monkeypatch.setattr(prep, "_static_gate", lambda runtime: _gate(hashes))
    monkeypatch.setattr(
        prep,
        "defender_scan",
        lambda staged, scanner=None: {"status": "passed", "exit_code": 0},
    )

    result = prep.stage_candidate(
        archive,
        destination,
        report_path=report,
    )

    assert result["native_executed"] is False
    assert result["approved_for_normal_backend"] is False
    assert result["hardware_test_ready"] is True
    assert report.is_file()
    assert (
        destination
        / "bin"
        / "runtime"
        / "dlssnr"
        / "neuroframe_engine_neural_rendering.dll"
    ).is_file()


def test_v10_research_stage_does_not_promote_postscan_hash_change(monkeypatch, tmp_path):
    archive = tmp_path / "v10.zip"
    archive.write_bytes(b"archive")
    destination = tmp_path / "runtime" / "candidate"
    report = tmp_path / "audit" / "report.json"

    gates = iter([
        _gate({"neuroframe_engine_neural_rendering.dll": "A" * 64}),
        _gate({"neuroframe_engine_neural_rendering.dll": "B" * 64}),
    ])

    monkeypatch.setattr(prep, "RuntimeManager", _Manager)
    monkeypatch.setattr(prep, "verify_artifact", lambda archive, spec: None)
    monkeypatch.setattr(prep, "extract_safe_zip", _fake_extract)
    monkeypatch.setattr(prep, "_static_gate", lambda runtime: next(gates))
    monkeypatch.setattr(
        prep,
        "defender_scan",
        lambda staged, scanner=None: {"status": "passed", "exit_code": 0},
    )

    with pytest.raises(RuntimeError, match="changed during Defender scan"):
        prep.stage_candidate(
            archive,
            destination,
            report_path=report,
        )

    assert not destination.exists()
    assert not report.exists()


def test_v10_defender_failure_is_fail_closed(monkeypatch, tmp_path):
    scanner = tmp_path / "MpCmdRun.exe"
    scanner.write_bytes(b"fake")
    monkeypatch.setattr(prep.os, "name", "nt")
    monkeypatch.setattr(
        prep.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=2,
            stdout="",
            stderr="threat or scanner failure",
        ),
    )

    with pytest.raises(RuntimeError, match="did not return a clean"):
        prep.defender_scan(tmp_path, scanner=scanner)
