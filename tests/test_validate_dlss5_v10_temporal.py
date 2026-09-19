from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pytest

from src.backends.dlss5_v10_protocol import OutputEvidence
import tools.validate_dlss5_v10_temporal as temporal


ROOT = Path(__file__).resolve().parents[1]


class FakeTemporalClient:
    def __init__(self, **kwargs):
        self.pid = 5151
        self.calls = 0
        self.aborted = False

    def start_native_temporal_experimental(
        self, runtime, preflight, *, acknowledgement
    ):
        assert acknowledgement == temporal.TEMPORAL_EXPERIMENT_ACK
        return {
            "native_loaded": False,
            "experimental_native_mode": True,
            "normal_backend_enabled": False,
            "bounded_contract": {
                "input": [256, 256],
                "processing_scale": 1.0,
                "max_frames": 3,
            },
        }

    def create(self, request):
        return {
            "native_loaded": True,
            "output_size": [256, 256],
            "initialization": {
                "gpu_name": "NVIDIA GeForce RTX 3070 Ti",
                "bridge_abi_version": 6,
                "gpu_ordinal": request.gpu_ordinal,
            },
        }

    def process_frame(self, frame):
        source = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(256, 256, 4).copy()
        self.calls += 1
        source[..., 0] = np.bitwise_xor(source[..., 0], 0x08 + self.calls)
        return OutputEvidence(
            width=256,
            height=256,
            timestamp=frame.timestamp,
            ngx_create_result=1,
            ngx_evaluate_result=1,
            cuda_result=0,
            scene_reset=int(frame.reset),
            scene_score=0.1 * self.calls,
            upload_bytes=256 * 256 * 4,
            download_bytes=256 * 256 * 4,
            rgba=source.tobytes(),
        )

    def close(self):
        return "CLOSED"

    def abort(self):
        self.aborted = True
        return "TERMINATED_OWNED_HOST"


def _patch_safe_environment(monkeypatch):
    monkeypatch.setattr(temporal, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(temporal, "V10ProtocolClient", FakeTemporalClient)
    monkeypatch.setattr(
        temporal,
        "assert_no_host_descendants",
        lambda pid, stage: {
            "stage": stage,
            "host_pid": pid,
            "descendant_count": 0,
            "descendants": [],
        },
    )
    monkeypatch.setattr(
        temporal, "install_temporary_firewall_block", lambda *args: None
    )
    monkeypatch.setattr(
        temporal, "remove_temporary_firewall_block", lambda *args: None
    )


def test_temporal_v10_fake_pass_runs_reset_then_two_nonreset_frames(
    monkeypatch, tmp_path
):
    _patch_safe_environment(monkeypatch)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = temporal.run_temporal(runtime, preflight, gpu_ordinal=0)

    assert report["status"] == "PASS"
    assert report["native_executed"] is True
    assert report["normal_backend_changed"] is False
    assert report["frame_count"] == 3
    assert report["reset_pattern"] == [True, False, False]
    assert report["unique_output_hashes"] == 3
    assert [item["reset"] for item in report["frames"]] == [True, False, False]
    assert all(item["nr_effect_observed"] for item in report["frames"])
    assert [item["stage"] for item in report["process_tree_checks"]] == [
        "after_hello",
        "after_create",
        "after_frame_0",
        "after_frame_1",
        "after_frame_2",
    ]
    assert report["close"] == "CLOSED"
    assert report["firewall_removed"] is True


def test_temporal_v10_rejects_stale_repeated_output(monkeypatch, tmp_path):
    class StaleClient(FakeTemporalClient):
        cached = None

        def process_frame(self, frame):
            output = super().process_frame(frame)
            if self.cached is None:
                self.cached = output.rgba
            return replace(output, rgba=self.cached)

    _patch_safe_environment(monkeypatch)
    monkeypatch.setattr(temporal, "V10ProtocolClient", StaleClient)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = temporal.run_temporal(runtime, preflight, gpu_ordinal=0)

    assert report["status"] == "FAIL"
    assert "repeated a previous output hash" in report["error"]


def test_temporal_v10_rejects_reset_state_mismatch(monkeypatch, tmp_path):
    class ResetMismatchClient(FakeTemporalClient):
        def process_frame(self, frame):
            output = super().process_frame(frame)
            return replace(output, scene_reset=1)

    _patch_safe_environment(monkeypatch)
    monkeypatch.setattr(temporal, "V10ProtocolClient", ResetMismatchClient)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = temporal.run_temporal(runtime, preflight, gpu_ordinal=0)

    assert report["status"] == "FAIL"
    assert "scene_reset=1, expected 0" in report["error"]


def test_temporal_v10_cli_is_blocked_without_exact_ack(monkeypatch, tmp_path):
    called = {"value": False}

    def fake_run(*args, **kwargs):
        called["value"] = True
        return {"status": "PASS"}

    monkeypatch.setattr(temporal, "run_temporal", fake_run)
    assert temporal.main([]) == 2
    assert called["value"] is False
    assert temporal.main(
        ["--execute", "--ack", "wrong", "--output", str(tmp_path / "x.json")]
    ) == 2
    assert called["value"] is False


def test_temporal_v10_wrapper_refreshes_preflight_before_execution():
    source = (ROOT / "tools" / "run_dlss5_v10_temporal.ps1").read_text(
        encoding="utf-8"
    )
    assert "[switch]$Execute" in source
    assert "audit_dlss5_v10.ps1" in source
    assert "prepare_dlss5_v10_candidate.py" in source
    assert "validate_dlss5_v10_temporal.py" in source
    assert "--ack BOUNDED_256_THREE_FRAME" in source
    assert source.index("& $audit -Archive $archivePath") < source.index(
        "& $python $prepare"
    )
    assert source.index("& $python $prepare") < source.index("& $python $validate")
    assert "DLSS5_V10_TEMPORAL_PASS" in source
