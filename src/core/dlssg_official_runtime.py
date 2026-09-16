"""Deterministic identity for the externally supplied NVIDIA NGX runtime."""

from __future__ import annotations

from pathlib import Path

from src.runtime_manager.core import sha256_file


# C55 loads the DLSS-G provider from the official runtime directory.  Keep the
# identity narrow and deterministic: unrelated driver files must not silently
# change an attestation.
REQUIRED_FILES = ("nvngx_dlssg.dll",)


def identity(directory: str | Path | None) -> str:
    path = Path(directory).expanduser().resolve() if directory else None
    if path is None or not path.is_dir():
        return "missing"
    entries = []
    for name in REQUIRED_FILES:
        candidate = path / name
        if not candidate.is_file():
            return "missing:" + name
        entries.append(f"{name}:{candidate.stat().st_size}:{sha256_file(candidate)}")
    return "|".join(entries)
