"""Build a deterministic source/launcher candidate without bundling third-party binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


FORBIDDEN_SUFFIXES = {".dll", ".exe", ".pdb", ".lib", ".obj"}


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def ensure_clean() -> None:
    working = subprocess.run(["git", "diff", "--quiet"], check=False)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], check=False)
    if working.returncode or staged.returncode:
        raise RuntimeError("source worktree must be clean; build from a committed revision")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _copy_external_runtime(source: Path | None, destination: Path, required: tuple[str, ...], label: str, relative_prefix: str) -> list[dict[str, object]]:
    if source is None:
        return []
    source = source.resolve()
    if not source.is_dir():
        raise RuntimeError(f"{label} runtime directory does not exist: {source}")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise RuntimeError(f"{label} runtime is missing: {', '.join(missing)}")
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return [{"path": f"{relative_prefix}/{path.relative_to(destination).as_posix()}", "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in sorted(destination.rglob("*")) if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() != ".pyc"]


def _copy_notice(source: Path | None, destination: Path, label: str) -> dict[str, object] | None:
    if source is None:
        return None
    source = source.resolve()
    if not source.is_file():
        raise RuntimeError(f"{label} license notice does not exist: {source}")
    payload = source.read_bytes()
    if len(payload) > 4 * 1024 * 1024 or b"\x00" in payload:
        raise RuntimeError(f"{label} license notice must be a small text file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return {"path": destination.relative_to(destination.parents[1]).as_posix(), "sha256": sha256(destination), "size_bytes": len(payload)}


def build(output: Path, source_root: Path, python_runtime: Path | None = None, ffmpeg_runtime: Path | None = None, python_notice: Path | None = None, ffmpeg_notice: Path | None = None, toolchain: Path | None = None) -> dict[str, object]:
    os.chdir(source_root)
    ensure_clean()
    commit = git("rev-parse", "HEAD")
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nve-portable-") as temporary:
        stage = Path(temporary) / "NVIDIA-Video-Enhancer"
        archive = Path(temporary) / "source.tar"
        with archive.open("wb") as stream:
            subprocess.run(["git", "archive", "--format=tar", "HEAD"], stdout=stream, check=True)
        stage.mkdir()
        with tarfile.open(archive) as handle:
            handle.extractall(stage, filter="data")
        for path in stage.rglob("*"):
            if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
                raise RuntimeError(f"refusing to package binary-like tracked file: {path.relative_to(stage)}")
        external = {
            "python": _copy_external_runtime(python_runtime, stage / "runtime" / "python", ("python.exe",), "Python", "runtime/python") if python_runtime else [],
            "ffmpeg": _copy_external_runtime(ffmpeg_runtime, stage / "runtime" / "tools" / "ffmpeg", ("ffmpeg.exe", "ffprobe.exe"), "FFmpeg", "runtime/tools/ffmpeg") if ffmpeg_runtime else [],
        }
        if python_runtime and python_notice is None:
            raise RuntimeError("Python runtime requires an explicit license notice")
        if ffmpeg_runtime and ffmpeg_notice is None:
            raise RuntimeError("FFmpeg runtime requires an explicit license notice")
        notices = {
            "python": _copy_notice(python_notice, stage / "licenses" / "PORTABLE_PYTHON_NOTICE.txt", "Python"),
            "ffmpeg": _copy_notice(ffmpeg_notice, stage / "licenses" / "FFMPEG_NOTICE.txt", "FFmpeg"),
        }
        toolchain_data = json.loads(toolchain.read_text(encoding="utf-8")) if toolchain else None
        manifest = {
            "schema": 1,
            "source_commit": commit,
            "builder_python": platform.python_version(),
            "portable_python": (toolchain_data or {}).get("python", {}).get("version") if toolchain_data else None,
            "platform": platform.platform(),
            "source_date_epoch": epoch,
            "binary_policy": "approved base runtime binaries are bundled; optional or unapproved feature runtimes remain external" if (python_runtime or ffmpeg_runtime) else "source-only; runtime binaries remain external",
            "external_runtime_files": external,
            "external_runtime_notices": notices,
            "toolchain": toolchain_data,
        }
        (stage / "build-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        files = sorted(path for path in stage.rglob("*") if path.is_file())
        sums = "\n".join(f"{sha256(path)}  {path.relative_to(stage).as_posix()}" for path in files) + "\n"
        (stage / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
        (stage / "SHA256SUMS.txt").write_text(sums, encoding="utf-8", newline="\n")
        files = sorted(path for path in stage.rglob("*") if path.is_file())
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
            for path in files:
                relative = path.relative_to(Path(temporary)).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                handle.writestr(info, path.read_bytes())
    return {"output": str(output), "sha256": sha256(output), "source_commit": commit}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--python-runtime", type=Path, help="explicit portable Python directory containing python.exe")
    parser.add_argument("--ffmpeg-runtime", type=Path, help="explicit portable FFmpeg directory containing ffmpeg.exe and ffprobe.exe")
    parser.add_argument("--python-notice", type=Path, help="license notice for the supplied portable Python runtime")
    parser.add_argument("--ffmpeg-notice", type=Path, help="license notice for the supplied portable FFmpeg runtime")
    parser.add_argument("--toolchain", type=Path, help="pinned portable toolchain metadata JSON")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.output, args.source_root.resolve(), args.python_runtime.resolve() if args.python_runtime else None, args.ffmpeg_runtime.resolve() if args.ffmpeg_runtime else None, args.python_notice.resolve() if args.python_notice else None, args.ffmpeg_notice.resolve() if args.ffmpeg_notice else None, args.toolchain.resolve() if args.toolchain else None), indent=2))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"portable candidate failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
