from __future__ import annotations

import tools.benchmark_dlss5_v10_quality as v10_quality


def test_v10_quality_benchmark_has_media_probe_dependency() -> None:
    assert callable(v10_quality.probe)
