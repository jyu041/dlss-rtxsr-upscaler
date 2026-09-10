import numpy as np

from src.backends.dlss5_metrics import (
    EFFECT_MIN_CHANGED_RATIO,
    effect_metrics,
    effect_observed,
    statistics,
)


def test_effect_metrics_ignore_alpha_and_hash_rgb_bytes():
    source = np.zeros((2, 2, 4), dtype=np.uint8)
    output = source.copy()
    output[..., 3] = 17
    output[0, 0, 0] = 10
    metrics = effect_metrics(source, output)
    assert metrics["changed_pixel_count"] == 1
    assert metrics["changed_pixel_ratio"] == 0.25
    assert metrics["max_absolute_difference"] == 10
    assert metrics["input_sha256"] != metrics["output_sha256"]


def test_effect_decision_requires_both_metrics():
    assert not effect_observed({"changed_pixel_ratio": EFFECT_MIN_CHANGED_RATIO, "mean_absolute_difference": 0})
    assert effect_observed({"changed_pixel_ratio": EFFECT_MIN_CHANGED_RATIO, "mean_absolute_difference": 1})


def test_statistics_p95_is_bounded_and_json_safe():
    result = statistics([1, 2, 3, 4, 5])
    assert result["median_ms"] == 3
    assert result["p95_ms"] == 4.8
    assert statistics([])["p95_ms"] is None
