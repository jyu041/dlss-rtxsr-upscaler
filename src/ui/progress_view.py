from html import escape

from src.core.jobs import JobProgress
from src.core.progress import format_duration


def progress_html(progress: JobProgress) -> str:
    percent = 0.0 if progress.percent is None else max(0.0, min(100.0, progress.percent))
    total = "—" if progress.state == "IDLE" or progress.frames_total is None else str(progress.frames_total)
    eta = "—" if progress.state == "IDLE" else ("Estimating..." if progress.eta_seconds is None and progress.state not in {"COMPLETED", "CANCELLED", "FAILED"} else format_duration(progress.eta_seconds or 0))
    fps = progress.smoothed_fps or progress.average_fps
    return (
        '<div class="job-progress">'
        f'<div class="progress-head"><strong>{escape(progress.phase)}</strong><span>{percent:.0f}%</span></div>'
        f'<div class="progress-track"><div class="progress-fill" style="width:{percent:.1f}%"></div></div>'
        f'<div class="progress-meta"><span>Frames: {"—" if progress.state == "IDLE" else f"{progress.frames_done} / {total}"}</span><span>FPS: {"—" if progress.state == "IDLE" else f"{fps:.2f}"}</span><span>Elapsed: {"—" if progress.state == "IDLE" else format_duration(progress.elapsed_seconds)}</span><span>ETA: {escape(eta)}</span></div>'
        f'<div class="progress-message">{escape(progress.message)}</div></div>'
    )
