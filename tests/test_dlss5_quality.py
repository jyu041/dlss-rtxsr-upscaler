import numpy as np

from src.backends.dlss5_quality import (
    TemporalResidualStabilizer,
    resolve_working_scale,
)


def _frame(value: int, width: int = 64, height: int = 48) -> np.ndarray:
    frame = np.full((height, width, 4), value, dtype=np.uint8)
    frame[..., 3] = 255
    return frame


def test_auto_working_scale_is_session_stable_and_resolution_aware():
    assert resolve_working_scale("auto", 1280, 720) == 1.0
    assert resolve_working_scale("auto", 1920, 1080) == 2.0 / 3.0
    assert resolve_working_scale("auto", 3840, 2160) == 0.5
    assert resolve_working_scale(0.875, 1920, 1080) == 0.875


def test_quality_compositor_is_identity_when_neural_equals_source():
    source = _frame(96)
    compositor = TemporalResidualStabilizer(
        shimmer_suppression=0.8,
        color_strength=0.0,
        tone_preservation=1.0,
    )
    output, telemetry = compositor.compose(source, source, reset=True)
    assert np.array_equal(output, source)
    assert telemetry.history_reset is True


def test_temporal_residual_stabilization_blends_neural_delta_not_source_motion():
    source = _frame(100)
    brighter = _frame(120)
    darker = _frame(80)
    compositor = TemporalResidualStabilizer(shimmer_suppression=0.5)
    first, _ = compositor.compose(source, brighter, reset=True)
    second, _ = compositor.compose(source, darker, reset=False)
    reset, _ = compositor.compose(source, darker, reset=True)
    assert np.all(first[..., :3] == 120)
    assert abs(float(second[..., :3].mean()) - 100.0) <= 2.0
    assert np.all(reset[..., :3] == 80)


def test_color_strength_zero_keeps_source_chroma_better_than_full_neural_color():
    source = np.zeros((48, 64, 4), dtype=np.uint8)
    source[..., 0] = 120
    source[..., 1] = 100
    source[..., 2] = 80
    source[..., 3] = 255
    neural = source.copy()
    neural[..., 0] = 190
    neural[..., 2] = 30
    full, _ = TemporalResidualStabilizer(color_strength=1.0).compose(source, neural, reset=True)
    preserved, _ = TemporalResidualStabilizer(color_strength=0.0).compose(source, neural, reset=True)
    full_chroma_error = np.abs(full[..., 0].astype(int) - source[..., 0]).mean() + np.abs(full[..., 2].astype(int) - source[..., 2]).mean()
    preserved_chroma_error = np.abs(preserved[..., 0].astype(int) - source[..., 0]).mean() + np.abs(preserved[..., 2].astype(int) - source[..., 2]).mean()
    assert preserved_chroma_error < full_chroma_error


def test_tone_preservation_removes_broad_luma_shift():
    source = _frame(100)
    neural = _frame(140)
    unpreserved, _ = TemporalResidualStabilizer(tone_preservation=0.0).compose(source, neural, reset=True)
    preserved, _ = TemporalResidualStabilizer(tone_preservation=1.0).compose(source, neural, reset=True)
    assert unpreserved[..., :3].mean() > 130
    assert abs(float(preserved[..., :3].mean()) - 100.0) <= 2.0
