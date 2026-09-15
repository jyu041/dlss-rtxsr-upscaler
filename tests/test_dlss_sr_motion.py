import numpy as np

from src.video.dlss_sr_motion import StandaloneDLSSMotion


def _square(x=0):
    frame = np.zeros((96, 128, 4), dtype=np.uint8)
    frame[32:64, 42 + x:74 + x, :3] = 255
    frame[..., 3] = 255
    return frame


def test_first_frame_resets_and_has_protocol_shape():
    result = StandaloneDLSSMotion(128, 96).process(_square())
    assert result.reset
    assert result.motion.shape == (96, 128, 2)
    assert result.motion.dtype == np.float32


def test_identical_frames_have_near_zero_motion():
    guide = StandaloneDLSSMotion(128, 96)
    guide.process(_square())
    result = guide.process(_square())
    assert not result.reset
    assert np.max(np.abs(result.motion)) < 0.1


def test_translated_frame_has_finite_nonzero_current_to_previous_flow():
    guide = StandaloneDLSSMotion(128, 96)
    guide.process(_square())
    result = guide.process(_square(8))
    assert not result.reset
    assert np.isfinite(result.motion).all()
    assert np.mean(np.abs(result.motion[..., 0])) > 0.05
    assert float(np.median(result.motion[35:61, 45:75, 0])) < -1.0


def test_scene_cut_resets_motion():
    guide = StandaloneDLSSMotion(128, 96)
    guide.process(_square())
    result = guide.process(np.full((96, 128, 4), 255, dtype=np.uint8))
    assert result.reset
    assert np.count_nonzero(result.motion) == 0
