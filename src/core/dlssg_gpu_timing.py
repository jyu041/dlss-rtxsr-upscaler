"""Parse optional D3D12 GPU timestamp diagnostics from an instrumented DLSS-G worker.

The production protocol remains v4.  Timestamp evidence is emitted on stderr so
older validated workers and clients remain wire-compatible.
"""

from __future__ import annotations

from collections import defaultdict
import re
import statistics
from typing import Iterable


_PATTERN = re.compile(
    r"^GPU_TIMESTAMP "
    r"frame=(?P<frame>\d+) "
    r"stage=(?P<stage>[a-z0-9_]+) "
    r"index=(?P<index>\d+) "
    r"ms=(?P<ms>\d+(?:\.\d+)?) "
    r"frequency=(?P<frequency>\d+)$"
)


def parse_gpu_timestamp(line: str) -> dict[str, int | float | str] | None:
    match = _PATTERN.match(line.strip())
    if not match:
        return None
    return {
        "frame": int(match.group("frame")),
        "stage": match.group("stage"),
        "index": int(match.group("index")),
        "ms": float(match.group("ms")),
        "frequency": int(match.group("frequency")),
    }


def summarize_gpu_timestamps(lines: Iterable[str]) -> dict[str, object]:
    records = [record for line in lines if (record := parse_gpu_timestamp(line)) is not None]
    stages: dict[str, list[float]] = defaultdict(list)
    frequencies: set[int] = set()
    for record in records:
        stages[str(record["stage"])].append(float(record["ms"]))
        frequencies.add(int(record["frequency"]))

    return {
        "available": bool(records),
        "records": records,
        "frequencies": sorted(frequencies),
        "stages_ms": {
            stage: {
                "count": len(values),
                "median": statistics.median(values),
                "mean": statistics.fmean(values),
                "min": min(values),
                "max": max(values),
            }
            for stage, values in sorted(stages.items())
        },
    }
