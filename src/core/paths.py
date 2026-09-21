from datetime import datetime
from pathlib import Path
import os, uuid

ROOT = Path(__file__).resolve().parents[2]
TEMP = ROOT / "temp"; OUTPUTS = ROOT / "outputs"; LOGS = ROOT / "logs"
for _p in (TEMP, OUTPUTS, LOGS, LOGS / "jobs"): _p.mkdir(parents=True, exist_ok=True)

def safe_input(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file() or p.suffix.lower() not in {".mp4", ".mkv", ".mov", ".webm", ".avi"}:
        raise ValueError("Choose an existing supported video file.")
    return p

def job_dir() -> tuple[str, Path]:
    jid = uuid.uuid4().hex[:12]
    p = TEMP / jid; p.mkdir()
    return jid, p

def aligned_dimensions(width: int, height: int, scale: float = 1.0, target: tuple[int, int] | None = None) -> tuple[int, int]:
    """Apply the reference implementation's 8-pixel output alignment."""
    if target is None:
        raw = (round(width * scale), round(height * scale))
    else:
        raw = target
    return max(8, round(raw[0] / 8) * 8), max(8, round(raw[1] / 8) * 8)

def _output_timestamp() -> str:
    """Return the local wall-clock timestamp used in user-facing filenames."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def output_path(source: Path, mode: str, container: str, scale: float = 1, multiplier: int = 2) -> Path:
    tag = (
        f"dlssg_{multiplier}x"
        if "Frame Generation" in mode
        else "dlss_sr"
        if mode.startswith("DLSS SR")
        else "dlss5_v10"
        if mode == "DLSS 5 v10 Experimental"
        else "dlss5"
        if mode.startswith("DLSS")
        else f"rtxvsr_{scale:g}x"
    )
    timestamp = _output_timestamp()
    suffix = container.lower()
    candidate = OUTPUTS / f"{source.stem}_{timestamp}_{tag}.{suffix}"
    if not candidate.exists():
        return candidate

    # One GPU job runs at a time, but repeated/manual calls can still land in
    # the same wall-clock second. Keep the human-readable second-level timestamp
    # and add a deterministic counter rather than ever reusing an existing name.
    index = 2
    while True:
        candidate = OUTPUTS / f"{source.stem}_{timestamp}_{index}_{tag}.{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
