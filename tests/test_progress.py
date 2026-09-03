from src.core.jobs import ProgressTracker
from src.core.progress import format_duration


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
