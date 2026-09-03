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

def output_path(source: Path, mode: str, container: str, scale: float = 1) -> Path:
    tag = "dlss5" if mode.startswith("DLSS") else f"rtxvsr_{scale:g}x"
    return OUTPUTS / f"{source.stem}_{tag}.{container.lower()}"
