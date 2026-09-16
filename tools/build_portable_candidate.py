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


def _copy_external_runtime(source: Path | None, destination: Path, required: tuple[str, ...], label: str) -> list[dict[str, object]]:
    if source is None:
        return []
    source = source.resolve()
    if not source.is_dir():
        raise RuntimeError(f"{label} runtime directory does not exist: {source}")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise RuntimeError(f"{label} runtime is missing: {', '.join(missing)}")
    shutil.copytree(source, destination)
    return [{"path": path.relative_to(destination).as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in sorted(destination.rglob("*")) if path.is_file()]


def build(output: Path, source_root: Path, python_runtime: Path | None = None, ffmpeg_runtime: Path | None = None) -> dict[str, object]:
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
            "python": _copy_external_runtime(python_runtime, stage / "runtime" / "python", ("python.exe",), "Python") if python_runtime else [],
            "ffmpeg": _copy_external_runtime(ffmpeg_runtime, stage / "runtime" / "tools" / "ffmpeg", ("ffmpeg.exe", "ffprobe.exe"), "FFmpeg") if ffmpeg_runtime else [],
        }
        manifest = {
            "schema": 1,
            "source_commit": commit,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "source_date_epoch": epoch,
            "binary_policy": "source-only; proprietary and unclear third-party runtimes remain external",
            "external_runtime_files": external,
        }
        (stage / "build-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        files = sorted(path for path in stage.rglob("*") if path.is_file())
        sums = "\n".join(f"{sha256(path)}  {path.relative_to(stage).as_posix()}" for path in files) + "\n"
        (stage / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
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
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.output, args.source_root.resolve(), args.python_runtime.resolve() if args.python_runtime else None, args.ffmpeg_runtime.resolve() if args.ffmpeg_runtime else None), indent=2))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"portable candidate failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
