from src.core.dlssg_gpu_timing import parse_gpu_timestamp, summarize_gpu_timestamps


def test_parse_gpu_timestamp_record():
    line = "GPU_TIMESTAMP frame=42 stage=dlssg_evaluate index=2 ms=3.125 frequency=1000000"
    assert parse_gpu_timestamp(line) == {
        "frame": 42,
        "stage": "dlssg_evaluate",
        "index": 2,
        "ms": 3.125,
        "frequency": 1000000,
    }


def test_parse_gpu_timestamp_ignores_unrelated_diagnostics():
    assert parse_gpu_timestamp("WORKER_GROUP_SYNC frame=1 gpuWaitMs=5.0") is None


def test_summarize_gpu_timestamps_groups_stages():
    summary = summarize_gpu_timestamps([
        "GPU_TIMESTAMP frame=1 stage=input_upload index=0 ms=1.0 frequency=1000",
        "GPU_TIMESTAMP frame=1 stage=dlssg_evaluate index=1 ms=2.0 frequency=1000",
        "GPU_TIMESTAMP frame=2 stage=dlssg_evaluate index=1 ms=4.0 frequency=1000",
        "noise",
    ])
    assert summary["available"] is True
    assert summary["frequencies"] == [1000]
    assert summary["stages_ms"]["input_upload"]["count"] == 1
    assert summary["stages_ms"]["dlssg_evaluate"]["median"] == 3.0
    assert summary["stages_ms"]["dlssg_evaluate"]["mean"] == 3.0


def test_empty_summary_is_explicitly_unavailable():
    summary = summarize_gpu_timestamps(["noise"])
    assert summary == {
        "available": False,
        "records": [],
        "frequencies": [],
        "stages_ms": {},
    }
