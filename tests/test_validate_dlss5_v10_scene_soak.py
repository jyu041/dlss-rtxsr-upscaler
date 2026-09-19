from pathlib import Path

import numpy as np
import pytest

from src.backends.dlss5_v10_protocol import OutputEvidence
import tools.validate_dlss5_v10_scene_soak as soak


ROOT = Path(__file__).resolve().parents[1]
CUT_INDEX = 40


def fake_frames() -> list[np.ndarray]:
    frames: list[np.ndarray] = []
    for index in range(soak.SOAK_FRAME_COUNT):
        value = 40 if index < CUT_INDEX else 205
        frame = np.full((256, 256, 4), value, dtype=np.uint8)
        frame[..., 3] = 255
        left = 30 + (index % 20) * 2
        frame[96:128, left:left + 24, :3] = np.array(
            [80 + index % 30, 125, 165], dtype=np.uint8
        )
        frames.append(frame)
    return frames


class FakeSoakClient:
    def __init__(self, **kwargs):
        self.pid = 8181
        self.mode = None
        self.history = 0

    def start_native_scene_soak_experimental(
        self, runtime, preflight, *, acknowledgement, mode
    ):
        assert acknowledgement == soak.SCENE_SOAK_EXPERIMENT_ACK
        self.mode = mode
        return {
            "native_loaded": False,
            "experimental_native_mode": True,
            "normal_backend_enabled": False,
            "scene_cut_mode": f"{mode}-soak",
            "bounded_contract": {
                "input": [256, 256],
                "processing_scale": 1.0,
                "max_frames": 128,
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
        amount = 2 + min(self.history, 12)
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
        return "TERMINATED_OWNED_HOST"


def patch_environment(monkeypatch, frames=None):
    frames = frames or fake_frames()
    monkeypatch.setattr(soak, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(soak, "V10ProtocolClient", FakeSoakClient)
    monkeypatch.setattr(
        soak,
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
                "frame_count": 128,
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
        soak,
        "assert_no_host_descendants",
        lambda pid, stage: {
            "stage": stage,
            "host_pid": pid,
            "descendant_count": 0,
            "descendants": [],
        },
    )
    monkeypatch.setattr(soak, "install_temporary_firewall_block", lambda *args: None)
    monkeypatch.setattr(soak, "remove_temporary_firewall_block", lambda *args: None)
    monkeypatch.setattr(
        soak,
        "_save_review_images",
        lambda *args, **kwargs: ["review.png"],
    )
    monkeypatch.setattr(
        soak,
        "_save_review_videos",
        lambda *args, **kwargs: [
            {
                "path": "triptych.mp4",
                "layout": "source | scene-aware | reset-control",
                "display_scale": kwargs.get("scale", 2),
            },
            {
                "path": "pair.mp4",
                "layout": "scene-aware | reset-control",
                "display_scale": kwargs.get("scale", 2),
            },
            {
                "path": "diff.mp4",
                "layout": "scene-aware | reset-control | amplified absolute difference",
                "display_scale": kwargs.get("scale", 2),
            },
        ],
    )


def test_motion_compensated_metric_is_zero_for_identical_static_residual():
    sources = []
    outputs = []
    for index in range(4):
        frame = np.full((64, 64, 4), 50 + index, dtype=np.uint8)
        frame[..., 3] = 255
        output = frame.copy()
        output[..., 0] = np.clip(
            output[..., 0].astype(np.int16) + 3, 0, 255
        ).astype(np.uint8)
        sources.append(frame)
        outputs.append(output)

    metrics = soak.motion_compensated_temporal_metrics(
        sources, outputs, cut_ids=set()
    )

    assert metrics["enhancement_residual_flicker_mae"]["count"] == 3
    assert metrics["enhancement_residual_flicker_mae"]["mean"] == pytest.approx(
        0.0, abs=1e-6
    )


def test_review_frame_composition_and_video_layouts(monkeypatch, tmp_path):
    sources = []
    scene = []
    reset = []
    for index in range(3):
        source = np.full((256, 256, 4), 40 + index, dtype=np.uint8)
        source[..., 3] = 255
        scene_frame = source.copy()
        reset_frame = source.copy()
        scene_frame[..., 0] = np.clip(
            scene_frame[..., 0].astype(np.int16) + 3 + index, 0, 255
        ).astype(np.uint8)
        reset_frame[..., 0] = np.clip(
            reset_frame[..., 0].astype(np.int16) + 1, 0, 255
        ).astype(np.uint8)
        sources.append(source)
        scene.append(scene_frame)
        reset.append(reset_frame)

    captured = []

    def fake_encode(path, frames, *, fps):
        materialized = list(frames)
        captured.append(
            {
                "name": path.name,
                "fps": fps,
                "count": len(materialized),
                "shape": materialized[0].shape,
                "last_shape": materialized[-1].shape,
                "max": int(np.max(materialized[-1])),
            }
        )
        return {
            "path": str(path),
            "frame_count": len(materialized),
            "fps": fps,
            "width": materialized[0].shape[1],
            "height": materialized[0].shape[0],
            "encoder": "fake",
            "crf": soak.REVIEW_CRF,
            "pixel_format": "rgb24",
        }

    monkeypatch.setattr(soak, "_encode_review_video", fake_encode)
    videos = soak._save_review_videos(
        tmp_path,
        sources,
        scene,
        reset,
        fps=29.97,
        scale=2,
    )

    assert [item["name"] for item in captured] == [
        "source-sceneaware-reset-2x.mp4",
        "sceneaware-reset-2x.mp4",
        "sceneaware-reset-diff8x-2x.mp4",
    ]
    assert [item["shape"] for item in captured] == [
        (560, 1536, 3),
        (560, 1024, 3),
        (560, 1536, 3),
    ]
    assert all(item["count"] == 3 for item in captured)
    assert all(item["fps"] == pytest.approx(29.97) for item in captured)
    assert [item["display_scale"] for item in videos] == [2, 2, 2]
    assert videos[2]["difference_gain"] == soak.REVIEW_DIFF_GAIN


def test_review_video_failure_does_not_invalidate_native_hardware_pass(
    monkeypatch, tmp_path
):
    patch_environment(monkeypatch)
    monkeypatch.setattr(
        soak,
        "_save_review_videos",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("ffmpeg unavailable")
        ),
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = soak.run_scene_soak(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=0,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "PASS"
    assert report["native_executed"] is True
    assert report["review_video_status"] == "FAIL"
    assert report["review_videos"] == []
    assert "ffmpeg unavailable" in report["review_video_error"]


def test_scene_soak_fake_pass(monkeypatch, tmp_path):
    patch_environment(monkeypatch)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = soak.run_scene_soak(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=0,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "PASS"
    assert report["native_executed"] is True
    assert report["normal_backend_changed"] is False
    assert report["scene_cut_frame_ids"] == [CUT_INDEX]
    assert report["scene_aware"]["reset_frame_ids"] == [0, CUT_INDEX]
    assert report["reset_control"]["reset_frame_ids"] == list(range(128))
    assert report["reset_frame_parity"]["0"]["identical"] is True
    assert report["reset_frame_parity"][str(CUT_INDEX)]["identical"] is True
    assert report["state_influence_observed"] is True
    assert CUT_INDEX not in report["state_influence_frame_ids"]
    assert 1 in report["state_influence_frame_ids"]
    scene_hashes = {
        frame["output_sha256"] for frame in report["scene_aware"]["frames"]
    }
    reset_hashes = {
        frame["output_sha256"] for frame in report["reset_control"]["frames"]
    }
    assert report["scene_aware"]["unique_output_hashes"] == len(scene_hashes)
    assert report["reset_control"]["unique_output_hashes"] == len(reset_hashes)
    assert len(scene_hashes) > 1
    assert len(reset_hashes) > 1
    assert report["scene_aware"]["close"] == "CLOSED"
    assert report["reset_control"]["close"] == "CLOSED"
    assert report["firewall_removed"] is True
    motion = report["motion_compensated_temporal_metrics"]
    assert motion["scene_aware"]["enhancement_residual_flicker_mae"]["count"] == 126
    assert motion["reset_control"]["enhancement_residual_flicker_mae"]["count"] == 126
    assert report["review_images"] == ["review.png"]
    assert report["review_video_status"] == "PASS"
    assert len(report["review_videos"]) == 3
    assert report["review_scale"] == 2


def test_scene_soak_rejects_no_cut_window(monkeypatch, tmp_path):
    frames = []
    for index in range(128):
        frame = np.full((256, 256, 4), 80 + index % 2, dtype=np.uint8)
        frame[..., 3] = 255
        frames.append(frame)
    patch_environment(monkeypatch, frames=frames)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    report = soak.run_scene_soak(
        tmp_path / "fake.mp4",
        runtime,
        preflight,
        gpu_ordinal=0,
        start_frame=0,
        review_dir=tmp_path / "review",
    )

    assert report["status"] == "FAIL"
    assert report["native_executed"] is False
    assert "no scene cut detected" in report["error"]


def test_scene_soak_cli_requires_exact_ack(monkeypatch, tmp_path):
    called = {"value": False}

    def fake_run(*args, **kwargs):
        called["value"] = True
        return {"status": "PASS"}

    monkeypatch.setattr(soak, "run_scene_soak", fake_run)
    args = ["--input", str(tmp_path / "clip.mp4")]
    assert soak.main(args) == 2
    assert called["value"] is False
    assert soak.main(args + ["--execute", "--ack", "wrong"]) == 2
    assert called["value"] is False


def test_scene_soak_cli_can_require_playable_review_videos(monkeypatch, tmp_path):
    monkeypatch.setattr(
        soak,
        "run_scene_soak",
        lambda *args, **kwargs: {
            "status": "PASS",
            "review_video_status": "FAIL",
            "review_video_error": "encoder failed",
        },
    )
    output = tmp_path / "report.json"
    result = soak.main(
        [
            "--input",
            str(tmp_path / "clip.mp4"),
            "--output",
            str(output),
            "--execute",
            "--ack",
            "BOUNDED_256_SCENE_AWARE_128",
            "--require-review-videos",
        ]
    )
    assert result == 3
    saved = output.read_text(encoding="utf-8")
    assert "encoder failed" in saved


def test_scene_soak_host_client_and_wrapper_are_separately_gated():
    host = (ROOT / "src" / "backends" / "dlss5_v10_host.py").read_text(
        encoding="utf-8"
    )
    client = (ROOT / "src" / "backends" / "dlss5_v10_client.py").read_text(
        encoding="utf-8"
    )
    wrapper = (ROOT / "tools" / "run_dlss5_v10_scene_soak.ps1").read_text(
        encoding="utf-8"
    )

    assert 'SCENE_SOAK_EXPERIMENT_ACK = "BOUNDED_256_SCENE_AWARE_128"' in host
    assert "--experimental-native-scene-soak-serve" in host
    assert "--experimental-native-scene-soak-reset-serve" in host
    assert "max_frames=128" in host
    assert "start_native_scene_soak_experimental" in client
    assert "SCENE_SOAK_EXPERIMENT_ACK" in client
    assert "[Alias('Input')]" in wrapper
    assert "--ack BOUNDED_256_SCENE_AWARE_128" in wrapper
    assert "--start-frame $StartFrame" in wrapper
    assert "--review-scale $ReviewScale" in wrapper
    assert "--require-review-videos" in wrapper
    assert "DLSS5_V10_REVIEW_VIDEO" in wrapper
    assert wrapper.index("& $audit -Archive $archivePath") < wrapper.index(
        "& $python $prepare"
    )
    assert wrapper.index("& $python $prepare") < wrapper.index("& $python $validate")
    assert "DLSS5_V10_SCENE_SOAK_PASS" in wrapper
