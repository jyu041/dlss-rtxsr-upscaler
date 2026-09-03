"""Shared frame-progress callback and presentation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .jobs import ProgressTracker


@dataclass(frozen=True)
class ProgressEvent:
    frame_index: int
    total_frames: int | None
    phase: str
    message: str = ""


def report_progress(callback, *, frame_index: int, total_frames: int | None, phase: str, message: str = "") -> None:
    if callback is not None:
        callback(ProgressEvent(frame_index, total_frames, phase, message))


def tracker_callback(tracker: ProgressTracker):
    def callback(event: ProgressEvent) -> None:
        tracker.update(frames_done=event.frame_index, frames_total=event.total_frames, phase=event.phase, state="PROCESSING" if event.phase == "PROCESSING" else event.phase, message=event.message)

    return callback


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "Unavailable"
    seconds = max(0, int(round(seconds)))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
