import numpy as np
import pytest

from src.core.mfg_quality import (
    frame_metrics,
    psnr_db,
    ssim_rgb,
    summarize_samples,
    withheld_groups,
)


def test_identical_frame_quality_is_perfect():
    frame = np.zeros((4, 5, 4), dtype=np.uint8)
    frame[..., 3] = 255
    metrics = frame_metrics(frame, frame.copy())
    assert metrics["identical"] is True
    assert metrics["mae"] == 0.0
    assert metrics["rmse"] == 0.0
    assert metrics["psnr_db"] is None
    assert metrics["ssim_rgb"] == pytest.approx(1.0)
    assert metrics["edge_mae"] is None
    assert metrics["edge_pixel_percent"] == 0.0
    assert psnr_db(frame, frame) is None
    assert ssim_rgb(frame, frame) == pytest.approx(1.0)


def test_quality_metrics_ignore_alpha_and_detect_rgb_error():
    reference = np.zeros((8, 8, 4), dtype=np.uint8)
    generated = reference.copy()
    reference[..., 3] = 255
    generated[..., 3] = 7
    assert frame_metrics(reference, generated)["identical"] is True

    generated[..., 0] = 10
    metrics = frame_metrics(reference, generated)
    assert metrics["identical"] is False
    assert metrics["mae"] > 0
    assert metrics["rmse"] > 0
    assert metrics["psnr_db"] is not None
    assert metrics["ssim_rgb"] < 1.0



def test_edge_metric_focuses_on_reference_high_contrast_boundaries():
    reference = np.zeros((8, 8, 4), dtype=np.uint8)
    reference[..., 3] = 255
    reference[:, 4:, :3] = 255

    generated = reference.copy()
    generated[:, 4, :3] = 0

    metrics = frame_metrics(reference, generated)
    assert metrics["edge_pixel_percent"] > 0.0
    assert metrics["edge_mae"] is not None
    assert metrics["edge_mae"] > metrics["mae"]


def test_summary_aggregates_edge_metrics_without_requiring_edges():
    rows = [
        {
            "generated_index": 1,
            "mae": 1.0,
            "rmse": 2.0,
            "psnr_db": 30.0,
            "ssim_rgb": 0.9,
            "edge_mae": 5.0,
            "edge_pixel_percent": 10.0,
            "identical": False,
        },
        {
            "generated_index": 1,
            "mae": 2.0,
            "rmse": 3.0,
            "psnr_db": 29.0,
            "ssim_rgb": 0.8,
            "edge_mae": None,
            "edge_pixel_percent": 0.0,
            "identical": False,
        },
    ]
    summary = summarize_samples(rows)["overall"]
    assert summary["mean_edge_mae"] == pytest.approx(5.0)
    assert summary["mean_edge_pixel_percent"] == pytest.approx(5.0)

def test_withheld_group_plan_for_4x():
    assert withheld_groups(13, 4) == [
        {
            "group": 0,
            "left_anchor": 0,
            "right_anchor": 4,
            "withheld": (1, 2, 3),
        },
        {
            "group": 1,
            "left_anchor": 4,
            "right_anchor": 8,
            "withheld": (5, 6, 7),
        },
        {
            "group": 2,
            "left_anchor": 8,
            "right_anchor": 12,
            "withheld": (9, 10, 11),
        },
    ]


@pytest.mark.parametrize("multiplier", [0, 1, 5])
def test_withheld_group_plan_rejects_invalid_multiplier(multiplier):
    with pytest.raises(ValueError, match="multiplier"):
        withheld_groups(10, multiplier)


def test_summary_keeps_generated_indices_separate():
    rows = [
        {
            "generated_index": 1,
            "mae": 1.0,
            "rmse": 2.0,
            "psnr_db": 30.0,
            "ssim_rgb": 0.9,
            "identical": False,
        },
        {
            "generated_index": 1,
            "mae": 3.0,
            "rmse": 4.0,
            "psnr_db": 20.0,
            "ssim_rgb": 0.7,
            "identical": False,
        },
        {
            "generated_index": 2,
            "mae": 0.0,
            "rmse": 0.0,
            "psnr_db": None,
            "ssim_rgb": 1.0,
            "identical": True,
        },
    ]
    summary = summarize_samples(rows)
    assert summary["count"] == 3
    assert summary["by_generated_index"]["1"]["count"] == 2
    assert summary["by_generated_index"]["1"]["mean_psnr_db"] == pytest.approx(25.0)
    assert summary["by_generated_index"]["2"]["identical_count"] == 1
    assert summary["overall"]["mean_edge_mae"] is None
    assert summary["overall"]["mean_edge_pixel_percent"] is None


def test_quality_metrics_require_uint8_equal_rgb_geometry():
    left = np.zeros((2, 2, 4), dtype=np.uint8)
    right = np.zeros((3, 2, 4), dtype=np.uint8)
    with pytest.raises(ValueError, match="equal RGB shapes"):
        frame_metrics(left, right)
    with pytest.raises(ValueError, match="uint8"):
        frame_metrics(left.astype(np.float32), left)
