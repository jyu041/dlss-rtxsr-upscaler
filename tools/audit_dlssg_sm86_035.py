"""Static-only identity and configuration audit for upstream dlssg_for_sm86 0.3.5.

This tool deliberately DOES NOT load or execute the proxy DLL. The current
NVIDIA Video Enhancer offline worker uses a different direct-host contract, so
0.3.5 is research input only until an adapter is proven. Identity is pinned to
the exact Git blobs at upstream commit 9621db573e07ed54f50c15bbb585ed9a7bdfac28.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
from pathlib import Path
import struct


UPSTREAM_COMMIT = "9621db573e07ed54f50c15bbb585ed9a7bdfac28"
VERSION_DLL_GIT_BLOB_SHA1 = "efd92261f2b74e0a0fb927d74bce7a1c0c2413f7"
INI_GIT_BLOB_SHA1 = "2c97d64f2239b7d511f7d0a36c16e149dd3329f6"


def git_blob_sha1(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1()
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def pe_machine(path: Path) -> int:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError("candidate is not a PE image")
        stream.seek(0x3C)
        offset_data = stream.read(4)
        if len(offset_data) != 4:
            raise RuntimeError("candidate has a truncated DOS header")
        pe_offset = struct.unpack("<I", offset_data)[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            raise RuntimeError("candidate has no PE signature")
        machine = stream.read(2)
        if len(machine) != 2:
            raise RuntimeError("candidate has a truncated COFF header")
        return struct.unpack("<H", machine)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version-dll", type=Path, required=True)
    parser.add_argument("--ini", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    dll = args.version_dll.expanduser().resolve()
    ini = args.ini.expanduser().resolve()
    if not dll.is_file() or not ini.is_file():
        raise FileNotFoundError("both --version-dll and --ini must be files")

    dll_blob = git_blob_sha1(dll)
    ini_blob = git_blob_sha1(ini)
    if dll_blob.lower() != VERSION_DLL_GIT_BLOB_SHA1:
        raise RuntimeError(
            f"version.dll is not upstream 0.3.5 blob {VERSION_DLL_GIT_BLOB_SHA1}: {dll_blob}"
        )
    if ini_blob.lower() != INI_GIT_BLOB_SHA1:
        raise RuntimeError(
            f"dlssg_sm86.ini is not upstream 0.3.5 blob {INI_GIT_BLOB_SHA1}: {ini_blob}"
        )
    if pe_machine(dll) != 0x8664:
        raise RuntimeError("0.3.5 proxy candidate is not x86-64 PE")

    parser_ini = configparser.ConfigParser(interpolation=None)
    parser_ini.read(ini, encoding="utf-8")
    optimized = parser_ini.getint("FrameGeneration", "Optimized")
    max_generated = parser_ini.getint("FrameGeneration", "MaxGeneratedFrames")
    enabled = parser_ini.getint("General", "Enabled")
    runtime_mode = parser_ini.get("Runtime", "Mode")
    if enabled != 1:
        raise RuntimeError("upstream candidate is unexpectedly disabled")
    if optimized != 1:
        raise RuntimeError("research candidate must use output-preserving Optimized=1")
    if max_generated != 3:
        raise RuntimeError("research candidate must retain the upstream safe 4X ceiling")
    if runtime_mode.strip().lower() != "bundled":
        raise RuntimeError("research candidate must retain bundled runtime mode")

    report = {
        "schema_version": 1,
        "status": "STATIC_PASS",
        "executed": False,
        "upstream_repository": "sdli1995/dlssg_for_sm86",
        "upstream_commit": UPSTREAM_COMMIT,
        "version_dll": {
            "path": str(dll),
            "size_bytes": dll.stat().st_size,
            "git_blob_sha1": dll_blob,
            "sha256": sha256(dll),
            "pe_machine": "AMD64",
        },
        "ini": {
            "path": str(ini),
            "git_blob_sha1": ini_blob,
            "sha256": sha256(ini),
            "optimized": optimized,
            "max_generated_frames": max_generated,
            "runtime_mode": runtime_mode,
        },
        "compatibility": {
            "direct_host_compatible": False,
            "reason": (
                "Upstream 0.3.x is a game-facing proxy architecture; the "
                "validated NVIDIA Video Enhancer C55/grid1 worker requires the "
                "older direct-host NGX export contract."
            ),
        },
        "activation": "BLOCKED_STATIC_RESEARCH_ONLY",
        "notes": [
            "No DLL was loaded or executed by this audit.",
            "Optimized=1 is the upstream output-preserving tier; lossy tiers 2/3 are excluded.",
            "The validated C55/grid1 runtime remains untouched and remains the application default.",
        ],
    }
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("DLSSG_035_STATIC_AUDIT_PASS executed=false activation=BLOCKED_STATIC_RESEARCH_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
