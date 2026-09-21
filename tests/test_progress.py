from src.core import jobs
from src.core.jobs import JobProgress, ProgressTracker
from src.core.progress import format_duration, tracker_callback, ProgressEvent
from src.ui.progress_view import progress_html


def test_progress_eta_and_completion_values():
    tracker = ProgressTracker()
    tracker.update(frames_total=100, phase="PROCESSING", frames_done=1)
    progress = tracker.update(frames_done=50)
    assert progress.percent == 50
    tracker.update(frames_done=100, state="COMPLETED", phase="COMPLETED")
    assert tracker.snapshot().percent == 100
    assert format_duration(65) == "01:05"
    assert format_duration(3665) == "01:01:05"


def test_unknown_total_has_no_eta():
    tracker = ProgressTracker()
    progress = tracker.update(frames_done=10, frames_total=None, phase="PROCESSING")
    assert progress.percent is None and progress.eta_seconds is None



def test_snapshot_wall_elapsed_advances_between_progress_callbacks(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(jobs.time, "perf_counter", lambda: clock[0])
    tracker = ProgressTracker()
    clock[0] = 102.0
    tracker.update(frames_done=1, frames_total=100, phase="PROCESSING", state="PROCESSING")
    clock[0] = 107.5
    assert tracker.snapshot().elapsed_seconds == 7.5


def test_dlssg_phase_is_counted_as_processing(monkeypatch):
    clock = [200.0]
    monkeypatch.setattr(jobs.time, "perf_counter", lambda: clock[0])
    tracker = ProgressTracker()
    callback = tracker_callback(tracker)
    callback(ProgressEvent(1, 100, "DLSS-G 2X", "frame 1"))
    clock[0] = 202.0
    callback(ProgressEvent(21, 100, "DLSS-G 2X", "frame 21"))
    progress = tracker.snapshot()
    assert progress.state == "PROCESSING"
    assert progress.average_fps == 10.5


def test_progress_view_prefers_stable_average_processing_fps():
    progress = JobProgress(
        phase="PROCESSING",
        frames_done=50,
        frames_total=100,
        percent=50.0,
        elapsed_seconds=12.0,
        current_fps=500.0,
        average_fps=25.0,
        smoothed_fps=450.0,
        eta_seconds=2.0,
        message="Processing",
        state="PROCESSING",
    )
    html = progress_html(progress)
    assert "Throughput: 25.00 frames/s" in html
    assert "Wall elapsed: 00:12" in html
    assert "Frame ETA: 00:02" in html
