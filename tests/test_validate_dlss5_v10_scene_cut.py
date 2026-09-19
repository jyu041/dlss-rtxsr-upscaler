from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.backends.dlss5_v10_protocol import OutputEvidence
import tools.validate_dlss5_v10_scene_cut as scene_gate


ROOT = Path(__file__).resolve().parents[1]
CUT_INDEX = 12


def fake_scene_frames() -> list[np.ndarray]:
    frames: list[np.ndarray] = []
    for index in range(scene_gate.SCENE_FRAME_COUNT):
        value = 35 if index < CUT_INDEX else 210
        frame = np.full((256, 256, 4), value, dtype=np.uint8)
        frame[..., 3] = 255
        left = 20 + (index % 10) * 5
        frame[100:124, left:left + 20, :3] = np.array(
            [70 + (index % 20), 120, 150], dtype=np.uint8
        )
        frames.append(frame)
    return frames


class FakeSceneClient:
    def __init__(self, **kwargs):
        self.pid = 7171
        self.mode = None
        self.history = 0
        self.aborted = False

    def start_native_scene_cut_experimental(
        self, runtime, preflight, *, acknowledgement, mode
    ):
        assert acknowledgement == scene_gate.SCENE_CUT_EXPERIMENT_ACK
        self.mode = mode
        return {
            "native_loaded": False,
            "experimental_native_mode": True,
            "normal_backend_enabled": False,
            "scene_cut_mode": mode,
            "bounded_contract": {
                "input": [256, 256],
                "processing_scale": 1.0,
                "max_frames": 32,
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
        if frame.reset:
            self.history = 0
        amount = 2 + min(self.history, 8)
        rgb = source[..., :3].astype(np.int16)
        rgb[..., 0] = np.clip(rgb[..., 0] + amount, 0, 255)
        source[..., :3] = rgb.astype(np.uint8)
        self.history += 1
        return OutputEvidence(
            width=256,
            height=256,
            timestamp=frame.timestamp,
            ngx_create_result=1,
            ngx_evaluate_result=1,
            cuda_result=0,
            scene_reset=int(frame.reset),
            scene_score=1.0 if frame.reset else 0.0,
            upload_bytes=256 * 256 * 4,
            download_bytes=256 * 256 * 4,
            rgba=source.tobytes(),
        )

    def close(self):
        return "CLOSED"

    def abort(self):
        self.aborted = True
        return "TERMINATED_OWNED_HOST"


def patch_safe_environment(monkeypatch, frames=None):
    frames = frames or fake_scene_frames()
    monkeypatch.setattr(scene_gate, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(scene_gate, "V10ProtocolClient", FakeSceneClient)
    monkeypatch.setattr(
        scene_gate,
        "decode_video_frames",
        lambda *args, **kwargs: (
            frames,
            {
                "path": "fake.mp4",
                "width": 640,
                "height": 480,
                "fps": 30.0,
                "reported_total_frames": 442,
                "start_frame": 0,
                "frame_count": 32,
                "preprocess": {
                    "method": "center-square-crop-then-area-resize",
                    "crop_box": {"left": 80, "top": 0, "width": 480, "height": 480},
                    "output": [256, 256],
                    "pixel_format": "rgba8",
                },
            },
        ),
    )
    monkeypatch.setattr(
        scene_gate,
        "assert_no_host_descendants",
        lambda pid, stage: {
            "stage": stage,
            "host_pid": pid,
            "descendant_count": 0,
            "descendants": [],
        },
    )
    monkeypatch.setattr(
        scene_gate, "install_temporary_firewall_block", lambda *args: None
    )
    monkeypatch.setattr(
        scene_gate, "remove_temporary_firewall_block", lambda *args: None
    )
    monkeypatch.setattr(
        scene_gate,
        "_save_cut_reviews",
        lambda *args, **kwargs: ["cut-review.png"],
    )


def test_scene_detector_finds_hard_cut():
    cuts = scene_gate.detect_scene_cuts(fake_scene_frames())
    assert [item["index"] for item in cuts] == [CUT_INDEX]
    assert cuts[0]["is_cut"] is True
    assert cuts[0]["rgb_mad"] >= 80.0


def test_scene_cut_fake_pass_proves_reset_parity(monkeypatch, tmp_path):
    patch_safe_environment(monkeypatch)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = scene_gate.run_scene_cut_gate(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=0,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "PASS"
    assert report["native_executed"] is True
    assert report["native_execution_attempted"] is True
    assert report["normal_backend_changed"] is False
    assert report["scene_cut_frame_ids"] == [CUT_INDEX]
    assert report["no_cut_reset"]["reset_frame_ids"] == [0]
    assert report["scene_aware"]["reset_frame_ids"] == [0, CUT_INDEX]
    assert report["reset_control"]["reset_frame_ids"] == list(range(32))
    assert report["scene_reset_matches_reset_control"] is True
    assert report["cut_frame_comparisons"][0][
        "scene_aware_vs_reset_control"
    ]["identical"] is True
    assert report["cut_frame_comparisons"][0][
        "no_cut_reset_vs_reset_control"
    ]["identical"] is False
    assert report["carryover_observed_at_cut_frame_ids"] == [CUT_INDEX]
    assert report["initial_reset_parity"]["no_cut_vs_reset"]["identical"] is True
    assert report["initial_reset_parity"]["scene_aware_vs_reset"]["identical"] is True
    assert report["no_cut_reset"]["close"] == "CLOSED"
    assert report["scene_aware"]["close"] == "CLOSED"
    assert report["reset_control"]["close"] == "CLOSED"
    assert report["firewall_removed"] is True
    assert report["review_images"] == ["cut-review.png"]


def test_scene_cut_gate_accepts_below_threshold_effect_as_diagnostic(
    monkeypatch, tmp_path
):
    class LowEffectClient(FakeSceneClient):
        def process_frame(self, frame):
            source = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(256, 256, 4).copy()
            # Deliberately below effect_observed(): one RGB value changes by one.
            source[0, 0, 0] = np.uint8((int(source[0, 0, 0]) + 1) % 256)
            return OutputEvidence(
                width=256,
                height=256,
                timestamp=frame.timestamp,
                ngx_create_result=1,
                ngx_evaluate_result=1,
                cuda_result=0,
                scene_reset=int(frame.reset),
                scene_score=1.0 if frame.reset else 0.0,
                upload_bytes=256 * 256 * 4,
                download_bytes=256 * 256 * 4,
                rgba=source.tobytes(),
            )

    patch_safe_environment(monkeypatch)
    monkeypatch.setattr(scene_gate, "V10ProtocolClient", LowEffectClient)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = scene_gate.run_scene_cut_gate(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=0,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "PASS"
    assert report["native_executed"] is True
    assert report["no_cut_reset"]["measurable_effect_frame_ids"] == []
    assert report["scene_aware"]["measurable_effect_frame_ids"] == []
    assert report["reset_control"]["measurable_effect_frame_ids"] == []
    assert report["no_cut_reset"]["byte_identical_to_input_frame_ids"] == []
    assert report["scene_reset_matches_reset_control"] is True


def test_scene_cut_gate_rejects_replayed_output_for_different_input(
    monkeypatch, tmp_path
):
    class ReplayClient(FakeSceneClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.first_output = None

        def process_frame(self, frame):
            output = super().process_frame(frame)
            if self.first_output is None:
                self.first_output = output.rgba
                return output
            return replace(output, rgba=self.first_output)

    patch_safe_environment(monkeypatch)
    monkeypatch.setattr(scene_gate, "V10ProtocolClient", ReplayClient)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = scene_gate.run_scene_cut_gate(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=0,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "FAIL"
    assert "previously produced for a different input" in report["error"]
    assert report["native_execution_attempted"] is True


def test_scene_cut_gate_rejects_window_without_cut(monkeypatch, tmp_path):
    frames = []
    for index in range(scene_gate.SCENE_FRAME_COUNT):
        frame = np.full((256, 256, 4), 60 + index % 2, dtype=np.uint8)
        frame[..., 3] = 255
        frames.append(frame)
    patch_safe_environment(monkeypatch, frames=frames)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = scene_gate.run_scene_cut_gate(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=0,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "FAIL"
    assert "no scene cut detected" in report["error"]
    assert report["native_executed"] is False


def test_scene_cut_gate_rejects_reset_that_does_not_match_control(
    monkeypatch, tmp_path
):
    class BrokenResetClient(FakeSceneClient):
        def process_frame(self, frame):
            output = super().process_frame(frame)
            if self.mode == "scene-aware" and frame.timestamp == CUT_INDEX:
                array = np.frombuffer(output.rgba, dtype=np.uint8).reshape(256, 256, 4).copy()
                array[0, 0, 0] ^= 1
                return replace(output, rgba=array.tobytes())
            return output

    patch_safe_environment(monkeypatch)
    monkeypatch.setattr(scene_gate, "V10ProtocolClient", BrokenResetClient)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = scene_gate.run_scene_cut_gate(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=0,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "FAIL"
    assert "did not reproduce reset-control output" in report["error"]
    assert report["scene_reset_matches_reset_control"] is False


def test_scene_cut_cli_requires_exact_ack(monkeypatch, tmp_path):
    called = {"value": False}

    def fake_run(*args, **kwargs):
        called["value"] = True
        return {"status": "PASS"}

    monkeypatch.setattr(scene_gate, "run_scene_cut_gate", fake_run)
    args = ["--input", str(tmp_path / "clip.mp4")]
    assert scene_gate.main(args) == 2
    assert called["value"] is False
    assert scene_gate.main(args + ["--execute", "--ack", "wrong"]) == 2
    assert called["value"] is False


def test_scene_cut_host_client_and_wrapper_are_separately_gated():
    host = (ROOT / "src" / "backends" / "dlss5_v10_host.py").read_text(
        encoding="utf-8"
    )
    client = (ROOT / "src" / "backends" / "dlss5_v10_client.py").read_text(
        encoding="utf-8"
    )
    wrapper = (ROOT / "tools" / "run_dlss5_v10_scene_cut.ps1").read_text(
        encoding="utf-8"
    )

    assert 'SCENE_CUT_EXPERIMENT_ACK = "BOUNDED_256_SCENE_CUT_32"' in host
    assert "--experimental-native-scene-no-reset-serve" in host
    assert "--experimental-native-scene-aware-serve" in host
    assert "--experimental-native-scene-reset-serve" in host
    assert "max_frames=32" in host
    assert "start_native_scene_cut_experimental" in client
    assert "SCENE_CUT_EXPERIMENT_ACK" in client
    assert "[Alias('Input')]" in wrapper
    assert "--ack BOUNDED_256_SCENE_CUT_32" in wrapper
    assert "--start-frame $StartFrame" in wrapper
    assert wrapper.index("& $audit -Archive $archivePath") < wrapper.index(
        "& $python $prepare"
    )
    assert wrapper.index("& $python $prepare") < wrapper.index("& $python $validate")
    assert "DLSS5_V10_SCENE_CUT_PASS" in wrapper
