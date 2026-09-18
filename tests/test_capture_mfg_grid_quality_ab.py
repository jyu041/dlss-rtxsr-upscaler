import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import tools.capture_mfg_grid_quality_ab as capture




def test_quality_runner_builds_selftests_then_invokes_capture_tool():
    root = Path(__file__).resolve().parents[1]
    source = (root / "tools" / "run_mfg_grid_quality_ab.ps1").read_text(encoding="utf-8")
    assert "build_validate_dlssg_instrumented.ps1" in source
    assert "capture_mfg_grid_quality_ab.py" in source
    assert "[Alias('Input')]" in source
    assert "[string]$InputPath" in source
    assert "[string]$Input," not in source
    assert "(Resolve-Path -LiteralPath $InputPath).Path" in source
    assert "[ValidateSet(2,4)]" in source
    assert "[ValidateRange(1,24)]" in source
    assert "[ValidateRange(0,1000000)]" in source
    assert "'--start-frame', $StartFrame" in source
    assert "'--worker', $worker" in source
    assert "'--runtime', $runtime" in source
    assert "'--official', $official" in source
    assert "'--preflight-only'" in source
    assert source.index("& $python.Source @preflightArgs") < source.index("& $build @buildArgs")



def test_quality_runner_input_alias_binds_before_native_build(tmp_path):
    if os.name != "nt":
        pytest.skip("PowerShell wrapper regression is Windows-only")

    root = Path(__file__).resolve().parents[1]
    script = root / "tools" / "run_mfg_grid_quality_ab.ps1"
    missing = tmp_path / "definitely-missing-input.mp4"
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Input",
            str(missing),
            "-Multiplier",
            "2",
            "-Groups",
            "1",
            "-StartFrame",
            "0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = (result.stdout + result.stderr).lower()
    assert result.returncode != 0
    assert "empty string" not in combined
    assert "cannot find path" in combined
    assert "pathnotfound" in combined


def test_evidence_root_namespaces_source_identity_and_multiplier(tmp_path):
    base = tmp_path / "quality"
    source = tmp_path / "My Clip.mp4"
    root2 = capture.evidence_root(base, source, "ABCDEF0123456789", 2, 0)
    root4 = capture.evidence_root(base, source, "ABCDEF0123456789", 4, 120)
    assert root2.parents[1].name == "My Clip-ABCDEF012345"
    assert root2.parent.name == "2x"
    assert root2.name == "start-00000000"
    assert root4.parent.name == "4x"
    assert root4.name == "start-00000120"
    assert root2 != root4

def test_grid_environment_is_restored(monkeypatch):
    monkeypatch.setenv("DLSSG_NVOF_DIRECTION", "both")
    monkeypatch.delenv("DLSSG_NVOF_GPU_FLOW", raising=False)
    monkeypatch.delenv("DLSSG_NVOF_OUTPUT_GRID", raising=False)
    with capture.nvof_grid_environment(4):
        assert os.environ["DLSSG_NVOF_DIRECTION"] == "forward"
        assert os.environ["DLSSG_NVOF_GPU_FLOW"] == "1"
        assert os.environ["DLSSG_NVOF_OUTPUT_GRID"] == "4"
    assert os.environ["DLSSG_NVOF_DIRECTION"] == "both"
    assert "DLSSG_NVOF_GPU_FLOW" not in os.environ
    assert "DLSSG_NVOF_OUTPUT_GRID" not in os.environ


def test_quality_delta_direction():
    grid1 = {
        "summary": {
            "overall": {
                "mean_mae": 10.0,
                "mean_rmse": 12.0,
                "mean_psnr_db": 25.0,
                "mean_ssim_rgb": 0.90,
                "mean_edge_mae": 15.0,
            }
        }
    }
    grid4 = {
        "summary": {
            "overall": {
                "mean_mae": 11.0,
                "mean_rmse": 13.5,
                "mean_psnr_db": 24.0,
                "mean_ssim_rgb": 0.88,
                "mean_edge_mae": 18.0,
            }
        }
    }
    delta = capture._quality_delta(grid1, grid4)
    assert delta["grid4_minus_grid1_mean_mae"] == pytest.approx(1.0)
    assert delta["grid4_minus_grid1_mean_rmse"] == pytest.approx(1.5)
    assert delta["grid4_minus_grid1_mean_psnr_db"] == pytest.approx(-1.0)
    assert delta["grid4_minus_grid1_mean_ssim_rgb"] == pytest.approx(-0.02)
    assert delta["grid4_minus_grid1_mean_edge_mae"] == pytest.approx(3.0)



def test_paired_quality_counts_per_sample_wins_and_deltas():
    def report(mae, psnr):
        return {
            "samples": [
                {
                    "group": 0,
                    "generated_index": 1,
                    "mae": mae[0],
                    "rmse": mae[0] + 1,
                    "psnr_db": psnr[0],
                    "ssim_rgb": 0.90 if mae[0] < 10 else 0.80,
                    "edge_mae": mae[0] + 2,
                },
                {
                    "group": 1,
                    "generated_index": 1,
                    "mae": mae[1],
                    "rmse": mae[1] + 1,
                    "psnr_db": psnr[1],
                    "ssim_rgb": 0.85,
                    "edge_mae": mae[1] + 3,
                },
            ]
        }

    result = capture._paired_quality(
        report((8.0, 10.0), (30.0, 25.0)),
        report((9.0, 9.0), (29.0, 26.0)),
    )
    assert len(result["samples"]) == 2
    assert result["wins"]["mae"] == {
        "grid1": 1,
        "grid4": 1,
        "tie": 0,
        "comparable": 2,
    }
    assert result["wins"]["psnr_db"] == {
        "grid1": 1,
        "grid4": 1,
        "tie": 0,
        "comparable": 2,
    }
    assert result["samples"][0]["grid4_minus_grid1"]["mae"] == pytest.approx(1.0)


def test_paired_quality_rejects_mismatched_sample_keys():
    grid1 = {"samples": [{"group": 0, "generated_index": 1}]}
    grid4 = {"samples": [{"group": 1, "generated_index": 1}]}
    with pytest.raises(RuntimeError, match="identical sample keys"):
        capture._paired_quality(grid1, grid4)


def test_require_grid_selected_fails_closed(monkeypatch):
    class Worker:
        diagnostics = ("NVOF_OUTPUT_GRID_SELECTED=1 flowWidth=1280 flowHeight=720",)

    monkeypatch.setattr(capture.time, "sleep", lambda *_args: None)
    ticks = iter([0.0, 0.0, 3.0])
    monkeypatch.setattr(capture.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="did not confirm requested NVOF output grid 4"):
        capture.require_grid_selected(Worker(), 4, timeout=2.0)


def test_review_candidates_prioritize_edge_regression():
    grid1 = {
        "samples": [
            {
                "group": 0, "generated_index": 1, "reference": "r0.png",
                "generated": "g1a.png", "mae": 10.0, "ssim_rgb": 0.90, "edge_mae": 15.0,
            },
            {
                "group": 1, "generated_index": 1, "reference": "r1.png",
                "generated": "g1b.png", "mae": 8.0, "ssim_rgb": 0.92, "edge_mae": 20.0,
            },
        ]
    }
    grid4 = {
        "samples": [
            {
                "group": 0, "generated_index": 1, "reference": "r0.png",
                "generated": "g4a.png", "mae": 11.0, "ssim_rgb": 0.89, "edge_mae": 16.0,
            },
            {
                "group": 1, "generated_index": 1, "reference": "r1.png",
                "generated": "g4b.png", "mae": 8.2, "ssim_rgb": 0.919, "edge_mae": 30.0,
            },
        ]
    }
    ranked = capture._review_candidates(grid1, grid4)
    assert ranked[0]["group"] == 1
    assert ranked[0]["grid4_minus_grid1_edge_mae"] == pytest.approx(10.0)
    assert ranked[0]["reference"] == "r1.png"


def test_temporal_report_reconstructs_anchor_and_generated_sequence(tmp_path):
    frames = []
    for value in (0, 10, 20):
        frame = np.zeros((2, 2, 4), dtype=np.uint8)
        frame[..., :3] = value
        frame[..., 3] = 255
        frames.append(frame)

    generated = tmp_path / "generated.png"
    capture._save_rgba(generated, frames[1])
    report = {
        "samples": [
            {
                "group": 0,
                "generated_index": 1,
                "generated": str(generated),
            }
        ]
    }
    temporal = capture._temporal_report(frames, report, multiplier=2, groups=1)
    assert temporal["count"] == 2
    assert temporal["mean_temporal_delta_mae"] == 0.0
    assert temporal["max_temporal_delta_mae"] == 0.0


def test_review_pack_writes_ranked_reference_grid_triptych(tmp_path):
    from PIL import Image

    paths = {}
    for name, value in (("reference", 10), ("grid1", 20), ("grid4", 30)):
        path = tmp_path / f"{name}.png"
        Image.new("RGB", (8, 6), (value, value, value)).save(path)
        paths[name] = path

    candidates = [
        {
            "group": 2,
            "generated_index": 1,
            "reference": str(paths["reference"]),
            "grid1_generated": str(paths["grid1"]),
            "grid4_generated": str(paths["grid4"]),
            "grid4_minus_grid1_edge_mae": 1.0,
            "grid4_minus_grid1_ssim_rgb": -0.01,
            "grid4_minus_grid1_mae": 0.5,
        }
    ]
    written = capture._write_review_pack(tmp_path, candidates)
    assert written[0]["rank"] == 1
    review_path = tmp_path / written[0]["review_image"]
    assert review_path.is_file()
    with Image.open(review_path) as image:
        assert image.size == (24, 48)

def test_capture_grid_writes_shared_reference_manifest(tmp_path, monkeypatch):
    width, height, multiplier, groups = 1280, 720, 2, 1
    frames = [
        np.zeros((height, width, 4), dtype=np.uint8),
        np.ones((height, width, 4), dtype=np.uint8),
        np.full((height, width, 4), 2, dtype=np.uint8),
    ]

    class Result:
        reset_only = True
        outputs = ()
        generated_count = 0

    class Generated:
        reset_only = False
        generated_count = 1
        outputs = (bytes([7]) * (width * height * 4),)

    class FakeWorker:
        def __init__(self, *args, **kwargs):
            self.calls = 0
            self.diagnostics = ("NVOF_OUTPUT_GRID_SELECTED=4 flowWidth=320 flowHeight=180",)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def create(self, *args, **kwargs):
            return {}
        def process(self, *args, **kwargs):
            self.calls += 1
            return Result() if self.calls == 1 else Generated()

    monkeypatch.setattr(capture, "DlssgWorker", FakeWorker)
    manifest = capture.capture_grid(
        grid=4,
        frames=frames,
        multiplier=multiplier,
        groups=groups,
        worker=tmp_path / "worker.exe",
        runtime=tmp_path / "version.dll",
        official=tmp_path / "official",
        output_root=tmp_path / "quality",
    )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["nvof_output_grid"] == 4
    assert data["multiplier"] == 2
    assert len(data["samples"]) == 1
    sample = data["samples"][0]
    assert Path(sample["reference"]).as_posix() == "references/g000_i1.png"
    assert Path(sample["generated"]).as_posix() == "grid4/generated/g000_i1.png"
    assert (tmp_path / "quality" / sample["reference"]).is_file()
    assert (tmp_path / "quality" / sample["generated"]).is_file()



def test_decode_source_respects_start_frame(tmp_path, monkeypatch):
    width, height = 1280, 720

    class Frame:
        def __init__(self, value):
            self.value = value
        def to_ndarray(self, format):
            frame = np.zeros((height, width, 4), dtype=np.uint8)
            frame[..., 0] = self.value
            return frame

    class Stream:
        average_rate = 60
        base_rate = 60

    class Container:
        streams = type("Streams", (), {"video": [Stream()]})()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def decode(self, stream):
            for value in range(6):
                yield Frame(value)

    monkeypatch.setattr(capture.av, "open", lambda *_args, **_kwargs: Container())
    frames, fps = capture.decode_source(tmp_path / "fake.mp4", 2, start_frame=3)
    assert fps == 60.0
    assert int(frames[0][0, 0, 0]) == 3
    assert int(frames[1][0, 0, 0]) == 4

def test_decode_source_accepts_640x480_natural_validation_geometry(tmp_path, monkeypatch):
    width, height = 640, 480

    class Frame:
        def __init__(self, value):
            self.value = value

        def to_ndarray(self, format):
            frame = np.zeros((height, width, 4), dtype=np.uint8)
            frame[..., 0] = self.value
            return frame

    class Stream:
        average_rate = 30000 / 1001
        base_rate = 30000 / 1001

    class Container:
        streams = type("Streams", (), {"video": [Stream()]})()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def decode(self, stream):
            for value in range(3):
                yield Frame(value)

    monkeypatch.setattr(capture.av, "open", lambda *_args, **_kwargs: Container())
    frames, fps = capture.decode_source(tmp_path / "fake.mp4", 3)
    assert len(frames) == 3
    assert frames[0].shape == (480, 640, 4)
    assert fps == pytest.approx(30000 / 1001)


def test_preflight_only_validates_source_without_worker_identity_checks(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "clip.mp4"
    input_path.write_bytes(b"placeholder")
    frames = [np.zeros((480, 640, 4), dtype=np.uint8)]

    def fake_decode(path, required_frames, *, start_frame=0):
        assert path == input_path.resolve()
        assert required_frames == 17
        assert start_frame == 0
        return frames, 30000 / 1001

    def identity_check_must_not_run(*_args, **_kwargs):
        raise AssertionError("worker identity validation ran during source-only preflight")

    monkeypatch.setattr(capture, "decode_source", fake_decode)
    monkeypatch.setattr(capture, "validate_identities", identity_check_must_not_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_mfg_grid_quality_ab.py",
            "--input",
            str(input_path),
            "--multiplier",
            "2",
            "--groups",
            "8",
            "--start-frame",
            "0",
            "--preflight-only",
        ],
    )
    assert capture.main() == 0
    output = capsys.readouterr().out
    assert '"status": "PREFLIGHT_PASS"' in output
    assert '"width": 640' in output
    assert '"height": 480' in output
    assert '"anchor_fps"' in output


@pytest.mark.parametrize("geometry", [(640, 360), (3840, 2160)])
def test_decode_source_rejects_unbounded_geometry(tmp_path, monkeypatch, geometry):
    # Source decoding itself is covered elsewhere; keep this test on the
    # explicit geometry contract by substituting a tiny fake PyAV container.
    width, height = geometry

    class Frame:
        def to_ndarray(self, format):
            return np.zeros((height, width, 4), dtype=np.uint8)

    class Stream:
        average_rate = 60
        base_rate = 60

    class Container:
        streams = type("Streams", (), {"video": [Stream()]})()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def decode(self, stream):
            yield Frame()

    monkeypatch.setattr(capture.av, "open", lambda *_args, **_kwargs: Container())
    with pytest.raises(RuntimeError, match="bounded to 1280x720 or 1920x1080"):
        capture.decode_source(tmp_path / "fake.mp4", 1)
