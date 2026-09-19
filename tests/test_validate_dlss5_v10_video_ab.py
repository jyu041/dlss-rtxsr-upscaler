from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.backends.dlss5_v10_protocol import OutputEvidence
import tools.validate_dlss5_v10_video_ab as video_ab


ROOT = Path(__file__).resolve().parents[1]


def fake_source_frames() -> list[np.ndarray]:
    frames: list[np.ndarray] = []
    for index in range(video_ab.VIDEO_FRAME_COUNT):
        frame = np.full((256, 256, 4), 40, dtype=np.uint8)
        frame[..., 3] = 255
        left = 20 + index * 4
        frame[100:124, left:left + 20, :3] = np.array(
            [80 + index, 120, 160], dtype=np.uint8
        )
        frames.append(frame)
    return frames


class FakeVideoABClient:
    def __init__(self, **kwargs):
        self.pid = 6161
        self.mode = None
        self.frame_index = 0
        self.aborted = False

    def start_native_video_ab_experimental(
        self, runtime, preflight, *, acknowledgement, mode
    ):
        assert acknowledgement == video_ab.VIDEO_AB_EXPERIMENT_ACK
        self.mode = mode
        return {
            "native_loaded": False,
            "experimental_native_mode": True,
            "normal_backend_enabled": False,
            "video_ab_mode": mode,
            "bounded_contract": {
                "input": [256, 256],
                "processing_scale": 1.0,
                "max_frames": 16,
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
        # Both fresh sessions produce the same first-frame output. Persistent
        # state then changes the enhancement strength on later frames.
        amount = 2 if self.mode == "reset-control" else 2 + self.frame_index
        rgb = source[..., :3].astype(np.int16)
        rgb[..., 0] = np.clip(rgb[..., 0] + amount, 0, 255)
        source[..., :3] = rgb.astype(np.uint8)
        output = OutputEvidence(
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
        self.frame_index += 1
        return output

    def close(self):
        return "CLOSED"

    def abort(self):
        self.aborted = True
        return "TERMINATED_OWNED_HOST"


def patch_safe_environment(monkeypatch):
    frames = fake_source_frames()
    monkeypatch.setattr(video_ab, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(video_ab, "V10ProtocolClient", FakeVideoABClient)
    monkeypatch.setattr(
        video_ab,
        "decode_video_frames",
        lambda *args, **kwargs: (
            frames,
            {
                "path": "fake.mp4",
                "width": 640,
                "height": 480,
                "fps": 30.0,
                "reported_total_frames": 442,
                "start_frame": 30,
                "frame_count": 16,
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
        video_ab,
        "assert_no_host_descendants",
        lambda pid, stage: {
            "stage": stage,
            "host_pid": pid,
            "descendant_count": 0,
            "descendants": [],
        },
    )
    monkeypatch.setattr(
        video_ab, "install_temporary_firewall_block", lambda *args: None
    )
    monkeypatch.setattr(
        video_ab, "remove_temporary_firewall_block", lambda *args: None
    )
    monkeypatch.setattr(
        video_ab,
        "_save_review_images",
        lambda *args, **kwargs: ["review-00.png", "review-08.png", "review-15.png"],
    )
    return frames


def test_preprocess_video_frame_center_crops_before_resize():
    source = np.zeros((480, 640, 3), dtype=np.uint8)
    rgba, crop = video_ab.preprocess_video_frame(source)
    assert rgba.shape == (256, 256, 4)
    assert crop == {"left": 80, "top": 0, "width": 480, "height": 480}
    assert np.all(rgba[..., 3] == 255)


def test_real_video_ab_fake_pass_observes_temporal_state(monkeypatch, tmp_path):
    patch_safe_environment(monkeypatch)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = video_ab.run_video_ab(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=30,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "PASS"
    assert report["native_executed"] is True
    assert report["normal_backend_changed"] is False
    assert report["frame_count"] == 16
    assert report["persistent"]["status"] == "PASS"
    assert report["reset_control"]["status"] == "PASS"
    assert report["frame0_identical"] is True
    assert report["state_influence_observed"] is True
    assert report["state_influence_frame_ids"] == list(range(1, 16))
    assert report["persistent"]["unique_output_hashes"] == 16
    assert report["reset_control"]["unique_output_hashes"] == 16
    assert report["persistent"]["close"] == "CLOSED"
    assert report["reset_control"]["close"] == "CLOSED"
    assert report["firewall_removed"] is True
    assert len(report["review_images"]) == 3
    assert "persistent_minus_reset" in report["temporal_metrics"]


def test_real_video_ab_rejects_no_state_influence(monkeypatch, tmp_path):
    class NoInfluenceClient(FakeVideoABClient):
        def process_frame(self, frame):
            source = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(256, 256, 4).copy()
            rgb = source[..., :3].astype(np.int16)
            rgb[..., 0] = np.clip(rgb[..., 0] + 2, 0, 255)
            source[..., :3] = rgb.astype(np.uint8)
            self.frame_index += 1
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
    monkeypatch.setattr(video_ab, "V10ProtocolClient", NoInfluenceClient)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = video_ab.run_video_ab(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=30,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "FAIL"
    assert "byte-identical to reset control" in report["error"]
    assert report["state_influence_observed"] is False


def test_real_video_ab_rejects_reset_state_mismatch(monkeypatch, tmp_path):
    class ResetMismatchClient(FakeVideoABClient):
        def process_frame(self, frame):
            output = super().process_frame(frame)
            if self.mode == "persistent" and frame.timestamp > 0:
                return replace(output, scene_reset=1)
            return output

    patch_safe_environment(monkeypatch)
    monkeypatch.setattr(video_ab, "V10ProtocolClient", ResetMismatchClient)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = video_ab.run_video_ab(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=30,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "FAIL"
    assert "scene_reset=1, expected 0" in report["error"]


def test_real_video_ab_cli_requires_exact_ack(monkeypatch, tmp_path):
    called = {"value": False}

    def fake_run(*args, **kwargs):
        called["value"] = True
        return {"status": "PASS"}

    monkeypatch.setattr(video_ab, "run_video_ab", fake_run)
    args = ["--input", str(tmp_path / "clip.mp4")]
    assert video_ab.main(args) == 2
    assert called["value"] is False
    assert video_ab.main(args + ["--execute", "--ack", "wrong"]) == 2
    assert called["value"] is False


def test_real_video_ab_host_client_and_wrapper_are_separately_gated():
    host = (ROOT / "src" / "backends" / "dlss5_v10_host.py").read_text(
        encoding="utf-8"
    )
    client = (ROOT / "src" / "backends" / "dlss5_v10_client.py").read_text(
        encoding="utf-8"
    )
    wrapper = (ROOT / "tools" / "run_dlss5_v10_video_ab.ps1").read_text(
        encoding="utf-8"
    )

    assert 'VIDEO_AB_EXPERIMENT_ACK = "BOUNDED_256_VIDEO_AB_16"' in host
    assert "--experimental-native-video-persistent-serve" in host
    assert "--experimental-native-video-reset-serve" in host
    assert "max_frames=16" in host
    assert "reset_every_frame=True" in host
    assert "start_native_video_ab_experimental" in client
    assert "VIDEO_AB_EXPERIMENT_ACK" in client
    assert "[Alias('Input')]" in wrapper
    assert "--ack BOUNDED_256_VIDEO_AB_16" in wrapper
    assert "--start-frame $StartFrame" in wrapper
    assert wrapper.index("& $audit -Archive $archivePath") < wrapper.index(
        "& $python $prepare"
    )
    assert wrapper.index("& $python $prepare") < wrapper.index("& $python $validate")
    assert "DLSS5_V10_VIDEO_AB_PASS" in wrapper
