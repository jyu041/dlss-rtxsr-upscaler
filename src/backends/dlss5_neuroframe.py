"""Static provenance gate for the separate DLSS5 Neuroframe candidate."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME = ROOT / "runtime" / "dlss5-neuroframe-v9"
EXPECTED_FILES = {
    "nvngx_dlssnr.dll": (165830144, "6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927"),
    "neuroframe_engine.dll": (570880, "2BDC5BFD59906DF7CB6DF98F78339D68F741B11256A26927A4C107425E7F46D4"),
    "neuroframe_caller.dll": (104960, "58E2850F96FC1B81A9154E059E3F3A42239440280C79E1CE41F6142CA9F1BAD4"),
}


@dataclass(frozen=True)
class NeuroframeStatus:
    state: str
    available: bool
    reason: str
    runtime: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def inspect_candidate(runtime: str | Path | None = None) -> NeuroframeStatus:
    root = Path(runtime or DEFAULT_RUNTIME).expanduser().resolve()
    if not root.is_dir():
        return NeuroframeStatus("NOT_INSTALLED", False, "DLSS5 Neuroframe v9 candidate is not installed", str(root))
    for name, (size, expected) in EXPECTED_FILES.items():
        path = root / name
        if not path.is_file():
            return NeuroframeStatus("IDENTITY_MISMATCH", False, f"Missing candidate file: {name}", str(root))
        if path.stat().st_size != size:
            return NeuroframeStatus("IDENTITY_MISMATCH", False, f"Candidate size mismatch: {name}", str(root))
        if _sha256(path) != expected:
            return NeuroframeStatus("IDENTITY_MISMATCH", False, f"Candidate SHA-256 mismatch: {name}", str(root))
    return NeuroframeStatus("STATIC_ONLY", False, "Pinned v9 files match; native execution/self-test is still required", str(root))
