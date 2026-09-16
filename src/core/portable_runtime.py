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


def inspect(root: str | Path, *, full: bool = False) -> dict[str, object]:
    root = Path(root).expanduser().resolve()
    manifest_path = root / "build-manifest.json"
    if not manifest_path.is_file():
        return {"state": "NOT_CONFIGURED", "detail": "No portable build manifest is present", "files": []}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("external_runtime_files", {})
        notices = manifest.get("external_runtime_notices", {})
    except (OSError, ValueError):
        return {"state": "BROKEN", "detail": "Portable build manifest is unreadable", "files": []}
    if not isinstance(expected, dict):
        return {"state": "BROKEN", "detail": "Portable build manifest has invalid runtime metadata", "files": []}
    if notices is not None and not isinstance(notices, dict):
        return {"state": "BROKEN", "detail": "Portable build manifest has invalid notice metadata", "files": []}
    checked = []
    for category, entries in expected.items():
        if not isinstance(entries, list):
            return {"state": "BROKEN", "detail": f"Invalid {category} runtime metadata", "files": checked}
        for entry in entries:
            relative = str(entry.get("path", ""))
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file():
                return {"state": "BROKEN", "detail": f"Missing portable runtime file: {relative}", "files": checked}
            expected_hash = str(entry.get("sha256", "")).upper()
            expected_size = entry.get("size_bytes")
            actual_size = path.stat().st_size
            checked.append({"category": category, "path": relative, "sha256": expected_hash if not full else _sha256(path), "size_bytes": actual_size})
            if (full and checked[-1]["sha256"] != expected_hash) or actual_size != expected_size:
                return {"state": "BROKEN", "detail": f"Portable runtime identity mismatch: {relative}", "files": checked}
    for category, entry in (notices or {}).items():
        if entry is None:
            continue
        if not isinstance(entry, dict):
            return {"state": "BROKEN", "detail": f"Invalid {category} notice metadata", "files": checked}
        relative = str(entry.get("path", ""))
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            return {"state": "BROKEN", "detail": f"Missing portable runtime notice: {relative}", "files": checked}
        expected_hash = str(entry.get("sha256", "")).upper()
        expected_size = entry.get("size_bytes")
        actual_size = path.stat().st_size
        checked.append({"category": f"notice:{category}", "path": relative, "sha256": expected_hash if not full else _sha256(path), "size_bytes": actual_size})
        if (full and checked[-1]["sha256"] != expected_hash) or actual_size != expected_size:
            return {"state": "BROKEN", "detail": f"Portable runtime notice identity mismatch: {relative}", "files": checked}
    required = (root / "runtime" / "python" / "python.exe", root / "runtime" / "tools" / "ffmpeg" / "ffmpeg.exe", root / "runtime" / "tools" / "ffmpeg" / "ffprobe.exe")
    if not all(path.is_file() for path in required):
        return {"state": "INCOMPLETE", "detail": "Portable runtime manifest is valid but required launcher tools are absent", "files": checked}
    detail = "Portable Python and media tool files are present; full hashes not checked at startup" if not full else "Portable Python and media tool identities match the build manifest"
    return {"state": "READY", "detail": detail, "files": checked}
