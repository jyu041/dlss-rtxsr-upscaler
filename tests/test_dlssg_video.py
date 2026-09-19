from pathlib import Path
from types import SimpleNamespace
import io

import pytest

from src.backends import dlssg as dlssg_backend
from src.backends.dlssg import DLSSGBackend
from src.video.dlssg import _bitstream_color_options, _hresult_failed, _read_frame, output_frame_count, scene_cut_metrics


class ShortReadStream:
    def __init__(self, data: bytes, chunk_size: int):
        self._stream = io.BytesIO(data)
        self._chunk_size = chunk_size

    def read(self, size: int) -> bytes:
        return self._stream.read(min(size, self._chunk_size))


def test_output_frame_count_duration_policy():
    assert output_frame_count(0) == 0
    assert output_frame_count(1) == 2
    assert output_frame_count(4) == 8
    assert output_frame_count(4, duplicate_terminal_frame=False) == 7
    assert output_frame_count(4, multiplier=3) == 12
    assert output_frame_count(4, multiplier=4) == 16
    assert output_frame_count(4, duplicate_terminal_frame=False, multiplier=3) == 10
    assert output_frame_count(4, duplicate_terminal_frame=False, multiplier=4) == 13


@pytest.mark.parametrize("multiplier", [0, 1, 5])
def test_output_frame_count_rejects_unsupported_multiplier(multiplier):
    with pytest.raises(ValueError, match="multiplier"):
        output_frame_count(4, multiplier=multiplier)


@pytest.mark.parametrize(
    ("code", "failed"),
    [
        ("0x00000000", False),
        ("0x00000001", False),
        ("0x887A0005", True),
        ("0x887A0006", True),
        ("garbage", True),
    ],
)
def test_hresult_failure_classification_matches_windows_semantics(code, failed):
    assert _hresult_failed(code) is failed


def test_raw_frame_reader_handles_short_pipe_reads():
    expected = bytes(range(32))
    stream = ShortReadStream(expected, 3)
    assert _read_frame(stream, len(expected)) == expected
    assert _read_frame(stream, len(expected)) == b""


def test_raw_frame_reader_rejects_truncated_frame():
    with pytest.raises(RuntimeError, match="truncated RGBA frame"):
        _read_frame(ShortReadStream(b"short", 2), 16)


def test_scene_cut_detector_rejects_small_motion_and_accepts_hard_cut():
    width = height = 64
    dark = bytes((16, 16, 16, 255)) * (width * height)
    small_change = bytes((20, 18, 16, 255)) * (width * height)
    bright = bytes((235, 235, 235, 255)) * (width * height)
    assert not scene_cut_metrics(dark, small_change, width, height)["is_cut"]
    decision = scene_cut_metrics(dark, bright, width, height)
    assert decision["is_cut"]
    assert decision["rgb_mad"] > 200
    assert decision["histogram_distance"] > 0.9


def test_scene_cut_detector_validates_packed_size():
    with pytest.raises(ValueError, match="tightly packed"):
        scene_cut_metrics(b"bad", b"bad", 2, 2)


def test_h264_bitstream_color_metadata_uses_source_vui_values():
    info = {"color_range": 1, "color_space": 1, "color_primaries": 1, "color_transfer": 1}
    assert _bitstream_color_options("h264_nvenc", info) == [
        "-bsf:v",
        "h264_metadata=video_full_range_flag=0:colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
    ]


def test_hevc_bitstream_color_metadata_preserves_full_range():
    info = {"color_range": 2, "color_space": 9, "color_primaries": 9, "color_transfer": 14}
    assert _bitstream_color_options("hevc_nvenc", info) == [
        "-bsf:v",
        "hevc_metadata=video_full_range_flag=1:colour_primaries=9:transfer_characteristics=14:matrix_coefficients=9",
    ]


def _configured_dlssg_identity(monkeypatch, tmp_path: Path, *, worker_hash: str):
    worker = tmp_path / "native" / "bin-instrumented" / "dlssg_sm86_offline.exe"
    worker.parent.mkdir(parents=True)
    worker.write_bytes(b"worker")
    runtime = tmp_path / "legacy" / "version.dll"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"runtime")
    official = tmp_path / "official"
    official.mkdir()

    monkeypatch.setattr(
        dlssg_backend,
        "RESEARCH_INSTRUMENTED_WORKER",
        worker.resolve(),
    )
    monkeypatch.setattr(
        dlssg_backend,
        "get_profile",
        lambda name: SimpleNamespace(runtime_sha256="RUNTIME_HASH", ini_sha256=None),
    )

    def fake_sha256(path):
        resolved = Path(path).resolve()
        if resolved == worker.resolve():
            return worker_hash
        if resolved == runtime.resolve():
            return "RUNTIME_HASH"
        raise AssertionError(f"unexpected identity path: {resolved}")

    monkeypatch.setattr(dlssg_backend, "sha256_file", fake_sha256)
    monkeypatch.setattr(
        dlssg_backend,
        "official_runtime_identity",
        lambda path: {"provider": str(Path(path).resolve())},
    )
    monkeypatch.setattr(dlssg_backend, "policy_satisfied", lambda identity: True)
    return worker, runtime, official


def test_default_dlssg_worker_policy_still_rejects_non_c55(monkeypatch, tmp_path: Path):
    worker, runtime, official = _configured_dlssg_identity(
        monkeypatch, tmp_path, worker_hash="RESEARCH_WORKER_HASH"
    )
    backend = DLSSGBackend(worker, runtime, official)
    status = backend.status()
    assert not status.available
    assert status.state == "IDENTITY MISMATCH"
    assert "verified C55 identity" in status.reason


def test_grid4_research_worker_policy_accepts_only_explicit_instrumented_candidate(
    monkeypatch, tmp_path: Path
):
    worker, runtime, official = _configured_dlssg_identity(
        monkeypatch, tmp_path, worker_hash="RESEARCH_WORKER_HASH"
    )
    backend = DLSSGBackend(
        worker,
        runtime,
        official,
        worker_identity_policy=dlssg_backend.WORKER_IDENTITY_GRID4_RESEARCH,
    )
    status = backend.status()
    assert status.available
    assert status.state == "RESEARCH CANDIDATE"
    assert backend.configuration.worker_identity_policy == (
        dlssg_backend.WORKER_IDENTITY_GRID4_RESEARCH
    )


def test_grid4_research_worker_policy_rejects_wrong_worker_path(monkeypatch, tmp_path: Path):
    worker, runtime, official = _configured_dlssg_identity(
        monkeypatch, tmp_path, worker_hash="RESEARCH_WORKER_HASH"
    )
    wrong_worker = tmp_path / "other" / "dlssg_sm86_offline.exe"
    wrong_worker.parent.mkdir()
    wrong_worker.write_bytes(b"other")

    original_sha = dlssg_backend.sha256_file
    monkeypatch.setattr(
        dlssg_backend,
        "sha256_file",
        lambda path: (
            "RESEARCH_WORKER_HASH"
            if Path(path).resolve() == wrong_worker.resolve()
            else original_sha(path)
        ),
    )
    backend = DLSSGBackend(
        wrong_worker,
        runtime,
        official,
        worker_identity_policy=dlssg_backend.WORKER_IDENTITY_GRID4_RESEARCH,
    )
    status = backend.status()
    assert not status.available
    assert status.state == "RESEARCH WORKER PATH MISMATCH"


def test_grid4_research_worker_policy_rejects_pinned_c55(monkeypatch, tmp_path: Path):
    worker, runtime, official = _configured_dlssg_identity(
        monkeypatch,
        tmp_path,
        worker_hash=dlssg_backend.VALIDATED_WORKER_SHA256,
    )
    backend = DLSSGBackend(
        worker,
        runtime,
        official,
        worker_identity_policy=dlssg_backend.WORKER_IDENTITY_GRID4_RESEARCH,
    )
    status = backend.status()
    assert not status.available
    assert status.state == "RESEARCH WORKER REQUIRED"


def test_backend_reports_missing_external_dependencies(tmp_path: Path):
    backend = DLSSGBackend(tmp_path / "worker.exe", tmp_path / "version.dll", tmp_path / "runtime")
    status = backend.status()
    assert not status.available
    assert "external community runtime" in status.reason


def test_backend_requires_configuration(tmp_path: Path):
    backend = DLSSGBackend(tmp_path / "worker.exe", tmp_path / "version.dll", tmp_path / "runtime")
    with pytest.raises(RuntimeError, match="unavailable"):
        backend.require_configuration()
