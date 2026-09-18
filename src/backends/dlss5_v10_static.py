"""Fail-closed static inspection boundary for Visual Enhancer v10.

This module never loads or executes the candidate DLLs.  It exists to complete
identity/ABI inspection before a separate executable adapter is considered.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from src.core.pe_static import PeFormatError, inspect_pe
from .dlss5_v10_contract import REQUIRED_EXPORTS, validate_static_contract


V10_FILES = (
    "nvngx_dlssnr.dll",
    "neuroframe_engine_neural_rendering.dll",
    "neuroframe_caller.dll",
)


@dataclass(frozen=True)
class V10StaticStatus:
    state: str
    valid: bool
    execution_allowed: bool
    detail: str
    evidence: dict[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def inspect_v10_runtime(
    runtime_dir: str | Path,
    *,
    expected_hashes: dict[str, str] | None = None,
) -> V10StaticStatus:
    root = Path(runtime_dir).expanduser().resolve()
    if not root.is_dir():
        return V10StaticStatus(
            "NOT_INSTALLED", False, False, f"v10 runtime directory is missing: {root}", {}
        )

    missing = [name for name in V10_FILES if not (root / name).is_file()]
    if missing:
        return V10StaticStatus(
            "INCOMPLETE",
            False,
            False,
            "missing required v10 files: " + ", ".join(missing),
            {"runtime_dir": str(root)},
        )

    validate_static_contract()
    evidence: dict[str, object] = {"runtime_dir": str(root), "files": {}}
    try:
        for name in V10_FILES:
            path = root / name
            pe = inspect_pe(path)
            record = {
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "pe": pe,
            }
            evidence["files"][name] = record
            if pe["architecture"] != "x86_64":
                return V10StaticStatus(
                    "ARCHITECTURE_MISMATCH",
                    False,
                    False,
                    f"{name} is not an x86_64 PE image",
                    evidence,
                )
    except (OSError, PeFormatError, RuntimeError) as exc:
        return V10StaticStatus("STATIC_AUDIT_FAILED", False, False, str(exc), evidence)

    bridge = evidence["files"]["neuroframe_engine_neural_rendering.dll"]
    exports = set(bridge["pe"]["exports"])
    missing_exports = sorted(set(REQUIRED_EXPORTS) - exports)
    if missing_exports:
        evidence["missing_bridge_exports"] = missing_exports
        return V10StaticStatus(
            "ABI_MISMATCH",
            False,
            False,
            "v10 bridge is missing required ABI-6 exports: " + ", ".join(missing_exports),
            evidence,
        )

    if expected_hashes is None:
        return V10StaticStatus(
            "STATIC_IDENTITY_REQUIRED",
            False,
            False,
            "v10 PE/ABI inspection passed, but exact extracted file hashes are not pinned yet",
            evidence,
        )

    normalized = {name: value.upper() for name, value in expected_hashes.items()}
    missing_hashes = [name for name in V10_FILES if name not in normalized]
    if missing_hashes:
        return V10StaticStatus(
            "STATIC_IDENTITY_REQUIRED",
            False,
            False,
            "expected hash set is incomplete: " + ", ".join(missing_hashes),
            evidence,
        )

    mismatches = []
    for name in V10_FILES:
        actual = str(evidence["files"][name]["sha256"])
        if actual != normalized[name]:
            mismatches.append(name)
    if mismatches:
        return V10StaticStatus(
            "IDENTITY_MISMATCH",
            False,
            False,
            "v10 file identity mismatch: " + ", ".join(mismatches),
            evidence,
        )

    return V10StaticStatus(
        "STATIC_AUDIT_COMPLETE",
        True,
        False,
        "v10 identity and ABI-6 static checks passed; execution remains deliberately disabled",
        evidence,
    )
