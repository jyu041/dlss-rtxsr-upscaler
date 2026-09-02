"""Opt-in local DLSS5 hardware checks; never run in ordinary CI."""

import os
import time
import subprocess
from pathlib import Path

import numpy as np
import pytest

from src.backends.dlss5 import DLSS5Backend
from src.backends.rtx_vsr import RTXVSRBackend
from src.video.dlss5 import render_dlss5
from src.video.stream import render_vsr


pytestmark = pytest.mark.skipif(
    os.environ.get("DLSS5_HARDWARE_TEST") != "1",
    reason="set DLSS5_HARDWARE_TEST=1 for local native execution",
)


def _frames(count, cut_at=None):
    for index in range(count):
        if cut_at is not None and index == cut_at:
            yield np.zeros((128, 128, 4), dtype=np.uint8) + np.array([0, 0, 0, 255], dtype=np.uint8)
            continue
        frame = np.zeros((128, 128, 4), dtype=np.uint8)
        frame[..., 0] = np.arange(128, dtype=np.uint8)[None, :]
        frame[..., 1] = np.arange(128, dtype=np.uint8)[:, None]
        frame[..., 2] = 64
        frame[..., 3] = 255
        left = (index * 4) % 112
        frame[48:64, left : left + 16, :3] = 255
        yield frame


def test_dlss5_temporal_and_scaling_matrix():
    backend = DLSS5Backend()
    assert backend.status().state == "EXPERIMENTAL READY"
    started = time.perf_counter()
    outputs = list(backend.process_frames(_frames(30, cut_at=15), width=128, height=128, frame_count=30))
    assert len(outputs) == 30
    assert outputs[0][1]["reset"] is True
    assert any(meta["reset"] for _, meta in outputs[1:])
    for factor, expected in ((1.5, 192), (2.0, 256)):
        options = backend.options(upscaling_mode=factor, nr_style="Natural", nr_intensity=.60, local_tone_strength=.40, local_structure_strength=.40, skin_structure_strength=.15, automatic_mask=False, dlss_model_preset="Default", motion_mode="optical_flow")
        scaled = list(backend.process_frames(_frames(5), width=128, height=128, frame_count=5, options=options))
        assert len(scaled) == 5
        assert scaled[-1][0].shape[:2] == (expected, expected)
    print(f"DLSS5 temporal/scaling matrix: {time.perf_counter() - started:.2f}s")


def test_dlss5_synthetic_preview_full_video_and_cancellation(tmp_path):
    source = tmp_path / "synthetic_unicode_тест.mp4"
    created = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=256x256:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    backend = DLSS5Backend()
    options = backend.options(upscaling_mode=1.0, nr_preset="Default", nr_style="Natural", nr_intensity=.60, local_tone_strength=.40, local_structure_strength=.40, skin_structure_strength=.15, automatic_mask=False, dlss_model_preset="Default", motion_mode="optical_flow")
    preview = tmp_path / "preview.mkv"
    preview_stats = render_dlss5(source, preview, backend, options, duration=3, codec="H.264")
    assert preview_stats["frames"] == 90
    assert preview_stats["audio_preserved"]
    assert preview.is_file()
    full = tmp_path / "full.mkv"
    full_stats = render_dlss5(source, full, backend, options, codec="H.264")
    assert full_stats["frames"] == 90
    assert full.is_file()
    from src.ui.app import do_frame
    before, after, status = do_frame(source, 0, "DLSS 5 only", "Super Resolution", 2.0, "ULTRA", 1.0, "Default", "Natural", .60, .40, .40, .15, "Off", "Default")
    assert Path(before).is_file()
    assert Path(after).is_file()
    assert "Feature-18 verified" in status

    class CancelAfterFive:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls > 5

    with pytest.raises(InterruptedError):
        list(backend.process_frames(_frames(30), width=128, height=128, frame_count=30, cancel=CancelAfterFive()))

    vsr_output = tmp_path / "vsr_regression.mp4"
    vsr_stats = render_vsr(source, vsr_output, RTXVSRBackend(), 2.0, "ULTRA", "Super Resolution")
    assert vsr_stats["frames"] == 90
    assert vsr_stats["audio_preserved"]
    assert vsr_output.is_file()
