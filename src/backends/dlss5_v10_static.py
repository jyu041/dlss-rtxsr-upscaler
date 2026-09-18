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

V10_EXPECTED_FILES = {
    "nvngx_dlssnr.dll": {
        "size_bytes": 165830144,
        "sha256": "6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927",
        "authenticode": "NotSigned",
    },
    "neuroframe_engine_neural_rendering.dll": {
        "size_bytes": 571904,
        "sha256": "F657D20E569F97DEC25E02141F64354CD4B3E1DC51FA1DFE48ACEEBCC3CC43D5",
        "authenticode": "NotSigned",
    },
    "neuroframe_caller.dll": {
        "size_bytes": 104960,
        "sha256": "B3611046837BC2F2E957A694CE0817E3C1B304BD653D0C7A193148E5BDD02437",
        "authenticode": "NotSigned",
    },
}

NETWORK_IMPORT_DLLS = {
    "WINHTTP.DLL",
    "WININET.DLL",
    "WS2_32.DLL",
    "URLMON.DLL",
}
NETWORK_IMPORT_SYMBOLS = {
    "CONNECT",
    "WSACONNECT",
    "INTERNETOPENA",
    "INTERNETOPENW",
    "INTERNETOPENURLA",
    "INTERNETOPENURLW",
    "WINHTTPOPEN",
    "WINHTTPOPENREQUEST",
    "URLDOWNLOADTOFILEA",
    "URLDOWNLOADTOFILEW",
}
PROCESS_IMPORT_SYMBOLS = {
    "CREATEPROCESSA",
    "CREATEPROCESSW",
    "CREATEPROCESSASUSERA",
    "CREATEPROCESSASUSERW",
    "CREATEPROCESSWITHLOGONW",
    "CREATEPROCESSWITHTOKENW",
    "WINEXEC",
    "SHELLEXECUTEA",
    "SHELLEXECUTEW",
    "SHELLEXECUTEEXA",
    "SHELLEXECUTEEXW",
}


def _sensitive_imports(pe: dict[str, object]) -> list[str]:
    findings: list[str] = []
    for dll in pe.get("imports", []):
        if str(dll).upper() in NETWORK_IMPORT_DLLS:
            findings.append(f"network-dll:{dll}")
    symbol_map = pe.get("import_symbols", {})
    if isinstance(symbol_map, dict):
        for dll, symbols in symbol_map.items():
            for symbol in symbols:
                upper = str(symbol).upper()
                if upper in NETWORK_IMPORT_SYMBOLS:
                    findings.append(f"network-symbol:{dll}!{symbol}")
                if upper in PROCESS_IMPORT_SYMBOLS:
                    findings.append(f"process-symbol:{dll}!{symbol}")
    return sorted(set(findings))


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
                "sensitive_imports": _sensitive_imports(pe),
            }
            pinned = V10_EXPECTED_FILES[name]
            if record["size_bytes"] != pinned["size_bytes"]:
                return V10StaticStatus(
                    "IDENTITY_MISMATCH",
                    False,
                    False,
                    f"{name} size does not match the pinned v10 evidence",
                    evidence,
                )
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
        expected_hashes = {
            name: str(record["sha256"])
            for name, record in V10_EXPECTED_FILES.items()
        }

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

    sensitive = {
        name: record["sensitive_imports"]
        for name, record in evidence["files"].items()
        if record["sensitive_imports"]
    }
    if sensitive:
        evidence["sensitive_import_review"] = sensitive
        return V10StaticStatus(
            "STATIC_REVIEW_REQUIRED",
            False,
            False,
            "v10 identity/ABI checks passed, but networking or process-launch imports require review",
            evidence,
        )

    return V10StaticStatus(
        "STATIC_AUDIT_COMPLETE",
        True,
        False,
        "v10 identity and ABI-6 static checks passed; execution remains deliberately disabled",
        evidence,
    )
