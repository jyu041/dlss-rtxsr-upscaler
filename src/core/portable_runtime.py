"""Integrity checks for an explicitly staged portable Python/media runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def inspect(root: str | Path) -> dict[str, object]:
    root = Path(root).expanduser().resolve()
    manifest_path = root / "build-manifest.json"
    if not manifest_path.is_file():
        return {"state": "NOT_CONFIGURED", "detail": "No portable build manifest is present", "files": []}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("external_runtime_files", {})
    except (OSError, ValueError):
        return {"state": "BROKEN", "detail": "Portable build manifest is unreadable", "files": []}
    if not isinstance(expected, dict):
        return {"state": "BROKEN", "detail": "Portable build manifest has invalid runtime metadata", "files": []}
    checked = []
    for category, entries in expected.items():
        if not isinstance(entries, list):
            return {"state": "BROKEN", "detail": f"Invalid {category} runtime metadata", "files": checked}
        for entry in entries:
            relative = str(entry.get("path", ""))
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file():
                return {"state": "BROKEN", "detail": f"Missing portable runtime file: {relative}", "files": checked}
            actual = _sha256(path)
            expected_hash = str(entry.get("sha256", "")).upper()
            expected_size = entry.get("size_bytes")
            checked.append({"category": category, "path": relative, "sha256": actual, "size_bytes": path.stat().st_size})
            if actual != expected_hash or path.stat().st_size != expected_size:
                return {"state": "BROKEN", "detail": f"Portable runtime identity mismatch: {relative}", "files": checked}
    required = (root / "runtime" / "python" / "python.exe", root / "runtime" / "tools" / "ffmpeg" / "ffmpeg.exe", root / "runtime" / "tools" / "ffmpeg" / "ffprobe.exe")
    if not all(path.is_file() for path in required):
        return {"state": "INCOMPLETE", "detail": "Portable runtime manifest is valid but required launcher tools are absent", "files": checked}
    return {"state": "READY", "detail": "Portable Python and media tool identities match the build manifest", "files": checked}
