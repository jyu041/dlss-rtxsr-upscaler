"""Managed provisioning for the validated experimental DLSS 5 v3 runtime.

This module downloads the public Merserk DLSS 5 Visual Enhancer v3.0 release,
verifies the complete archive and the exact five-file runtime identity previously
validated by this project, scans the staged payload with Microsoft Defender,
records Authenticode observations, installs an exact outbound firewall block for
the worker, writes the local approval manifest, and optionally runs the existing
Feature-18 hardware self-test.

The upstream archive is never redistributed by this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNTIME_DIR = ROOT / "runtime" / "dlss5-v3"
APPROVAL_PATH = RUNTIME_DIR / "approval.json"

RELEASE_PAGE = "https://github.com/Merserk/dlss5-visual-enhancer/releases/tag/3.0"
RELEASE_URL = (
    "https://github.com/Merserk/dlss5-visual-enhancer/releases/download/3.0/"
    "DLSS.5.Visual.Enhancer.v3.0.zip"
)
ARCHIVE_SIZE_BYTES = 466_919_995
ARCHIVE_SHA256 = "6F0590D81677484F4ECDFAA5C44FC2A0E1A3835D33EEFC59D656E6C3BCF35F6A"

EXPECTED_RUNTIME_SHA256 = {
    "nvngx.dll": "AE871BF387B84E59154DD666BBB6C0E03F466FAA2BA99687D7144C13E69F3DDF",
    "renodx-dlss5.addon64": "D5ADF82EB44B065F4C590AC91FE824BAB07AFEA0EB9F994BDE936710C8593952",
    "nvngx_dlssnr.dll": "6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927",
    "dxgi.dll": "0CEE63F9C9F13F3AC909C5B4903F4DBB4B719A7AB3B4F13B0DEAF83C814B94F7",
    "nvngx_dlss.dll": "C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E",
}

APPROVAL_HASH_KEYS = {
    "nvngx.dll": "worker_sha256",
    "renodx-dlss5.addon64": "renodx_sha256",
    "nvngx_dlssnr.dll": "dlssnr_sha256",
    "dxgi.dll": "dxgi_sha256",
    "nvngx_dlss.dll": "dlss_sha256",
}

FIREWALL_RULE_NAME = "NVIDIA Video Enhancer DLSS5 v3 outbound block"

NOTICE = f"""
DLSS 5 v3 is experimental.

This action downloads the public DLSS 5 Visual Enhancer v3.0 archive directly
from its upstream GitHub release ({ARCHIVE_SIZE_BYTES / 1_000_000:.0f} MB),
verifies the pinned archive SHA-256 and the exact five runtime-file SHA-256
values validated by this project, scans the staged runtime with Microsoft
Defender, records Authenticode results, creates an outbound Windows Firewall
block for the exact worker executable, and runs the synthetic Feature-18
self-test.

The files are not owned or redistributed by this repository. NVIDIA, ReShade,
RenoDX, and upstream terms continue to apply. A successful setup enables the
backend only as EXPERIMENTAL READY.
""".strip()


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _safe_member_name(name: str) -> str:
    raw = name.replace("\\", "/")
    path = PurePosixPath(raw)
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if not raw or raw.startswith("/") or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe archive member: {name}")
    for part in path.parts:
        if not part or part.endswith((".", " ")) or ":" in part:
            raise ValueError(f"unsafe archive member: {name}")
        if part.split(".", 1)[0].upper() in reserved:
            raise ValueError(f"unsafe archive member: {name}")
    return str(path)


def _runtime_relative(normalized: str) -> str | None:
    folded = normalized.casefold()
    marker = "bin/runtime/"
    if folded.startswith(marker):
        return normalized[len(marker):]
    embedded = "/" + marker
    index = folded.find(embedded)
    if index < 0:
        return None
    return normalized[index + len(embedded):]


def select_runtime_members(archive: Path) -> dict[str, zipfile.ZipInfo]:
    """Return the unique five validated runtime members from a pinned archive.

    The release layout may contain a top-level directory, so matching is rooted
    at the ``bin/runtime/`` marker rather than a guessed ZIP prefix. The entire
    member namespace is still checked for path traversal, symlinks, and
    case-insensitive collisions before any extraction occurs.
    """

    expected = {name.casefold(): name for name in EXPECTED_RUNTIME_SHA256}
    selected: dict[str, zipfile.ZipInfo] = {}
    seen: set[str] = set()

    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            normalized = _safe_member_name(info.filename)
            folded = normalized.casefold()
            if folded in seen:
                raise ValueError(f"case-insensitive duplicate archive member: {info.filename}")
            seen.add(folded)
            if info.is_dir():
                continue

            unix_mode = (info.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise ValueError(f"symlink archive member is not allowed: {info.filename}")

            relative = _runtime_relative(normalized)
            if relative is None or "/" in relative:
                continue
            canonical = expected.get(relative.casefold())
            if canonical is None:
                continue
            if canonical in selected:
                raise ValueError(f"multiple archive members map to required runtime file: {canonical}")
            selected[canonical] = info

    missing = sorted(set(EXPECTED_RUNTIME_SHA256) - set(selected))
    if missing:
        raise ValueError(f"archive is missing required DLSS5 v3 files: {', '.join(missing)}")
    return selected


def verify_runtime_files(runtime_dir: Path) -> dict[str, str]:
    actual: dict[str, str] = {}
    for name, expected in EXPECTED_RUNTIME_SHA256.items():
        path = runtime_dir / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing required DLSS5 v3 runtime file: {path}")
        digest = sha256_file(path)
        actual[name] = digest
        if digest != expected:
            raise ValueError(f"DLSS5 v3 hash mismatch for {name}: {digest} != {expected}")
    extras = sorted(
        path.name
        for path in runtime_dir.iterdir()
        if path.is_file() and path.name not in EXPECTED_RUNTIME_SHA256
    )
    if extras:
        raise ValueError(f"staged DLSS5 v3 runtime contains unexpected files: {', '.join(extras)}")
    return actual


def verify_archive(path: Path) -> None:
    if path.stat().st_size != ARCHIVE_SIZE_BYTES:
        raise ValueError(
            f"DLSS5 v3 archive size mismatch: {path.stat().st_size} != {ARCHIVE_SIZE_BYTES}"
        )
    digest = sha256_file(path)
    if digest != ARCHIVE_SHA256:
        raise ValueError(f"DLSS5 v3 archive SHA-256 mismatch: {digest} != {ARCHIVE_SHA256}")


def download_archive(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        RELEASE_URL, headers={"User-Agent": "NVIDIA-Video-Enhancer-DLSS5-provisioner"}
    )
    temporary = target.with_suffix(target.suffix + ".download")
    temporary.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            final_url = str(response.geturl())
            if not final_url.lower().startswith("https://"):
                raise ValueError(f"DLSS5 download redirected to non-HTTPS URL: {final_url}")
            total = int(response.headers.get("Content-Length") or 0)
            copied = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                copied += len(block)
                if total:
                    print(
                        f"\rDLSS5 v3 download: {copied}/{total} bytes ({copied / total:.0%})",
                        end="",
                        flush=True,
                    )
                else:
                    print(f"\rDLSS5 v3 download: {copied} bytes", end="", flush=True)
        print()
        verify_archive(temporary)
        os.replace(temporary, target)
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def extract_verified_runtime(archive: Path, destination: Path) -> dict[str, str]:
    selected = select_runtime_members(archive)
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as handle:
        for name, info in selected.items():
            target = destination / name
            with handle.open(info) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
    return verify_runtime_files(destination)


def authenticode_report(runtime_dir: Path) -> dict[str, Any]:
    files = [str((runtime_dir / name).resolve()) for name in EXPECTED_RUNTIME_SHA256]
    literal_array = ",".join("'" + item.replace("'", "''") + "'" for item in files)
    script = (
        f"$files=@({literal_array}); "
        "$items=@($files | ForEach-Object { "
        "$s=Get-AuthenticodeSignature -LiteralPath $_; "
        "[pscustomobject]@{file=[IO.Path]::GetFileName($_);"
        "status=$s.Status.ToString();"
        "status_message=$s.StatusMessage;"
        "signer_subject=$(if($s.SignerCertificate){$s.SignerCertificate.Subject}else{$null});"
        "signer_thumbprint=$(if($s.SignerCertificate){$s.SignerCertificate.Thumbprint}else{$null})} "
        "}); $items | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Authenticode inspection failed")
    try:
        parsed = json.loads(result.stdout.strip() or "[]")
    except ValueError as exc:
        raise RuntimeError("Authenticode inspection returned invalid JSON") from exc
    items = parsed if isinstance(parsed, list) else [parsed]
    return {"tool": "Get-AuthenticodeSignature", "completed": True, "files": items}


def _defender_candidates() -> list[Path]:
    candidates: list[Path] = []
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "Windows Defender" / "MpCmdRun.exe")
    program_data = os.environ.get("ProgramData")
    if program_data:
        platform = Path(program_data) / "Microsoft" / "Windows Defender" / "Platform"
        if platform.is_dir():
            candidates.extend(
                sorted(platform.glob("*/MpCmdRun.exe"), key=lambda path: path.parent.name, reverse=True)
            )
    return candidates


def defender_scan(runtime_dir: Path) -> dict[str, Any]:
    scanner = next((path for path in _defender_candidates() if path.is_file()), None)
    if scanner is None:
        raise RuntimeError(
            "Microsoft Defender MpCmdRun.exe was not found; automatic DLSS5 approval requires a malware scan"
        )
    result = subprocess.run(
        [
            str(scanner),
            "-Scan",
            "-ScanType",
            "3",
            "-File",
            str(runtime_dir.resolve()),
            "-DisableRemediation",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    report = {
        "tool": str(scanner),
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }
    if result.returncode:
        raise RuntimeError(
            "Microsoft Defender did not return a clean scan result "
            f"(exit {result.returncode}); DLSS5 approval was not created"
        )
    return report


def _powershell_quote(value: str) -> str:
    return value.replace("'", "''")


def install_firewall_block(worker: Path) -> dict[str, Any]:
    worker = worker.resolve()
    with tempfile.TemporaryDirectory(prefix="nve-dlss5-firewall-") as temporary:
        script_path = Path(temporary) / "install_firewall.ps1"
        script_path.write_text(
            "$ErrorActionPreference='Stop'\n"
            f"$name='{_powershell_quote(FIREWALL_RULE_NAME)}'\n"
            f"$program='{_powershell_quote(str(worker))}'\n"
            "Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | "
            "Remove-NetFirewallRule -ErrorAction SilentlyContinue\n"
            "New-NetFirewallRule -DisplayName $name -Direction Outbound -Action Block "
            "-Program $program -Profile Any -Enabled True | Out-Null\n",
            encoding="utf-8",
        )
        argument = (
            "-NoProfile -ExecutionPolicy Bypass -File "
            f"\"{str(script_path).replace(chr(34), chr(34) * 2)}\""
        )
        command = (
            "$p=Start-Process -FilePath 'powershell.exe' "
            f"-ArgumentList '{_powershell_quote(argument)}' "
            "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                result.stderr.strip()
                or "Windows Firewall rule creation failed or the elevation request was cancelled"
            )

    from src.backends.dlss5 import firewall_status

    status = firewall_status(worker)
    if not status.get("valid"):
        raise RuntimeError(f"DLSS5 outbound firewall block could not be verified: {status.get('reason')}")
    return {
        "rule_name": FIREWALL_RULE_NAME,
        "program": str(worker),
        "direction": "Outbound",
        "action": "Block",
        "verified": True,
    }


def activate_runtime(staged: Path, target: Path = RUNTIME_DIR) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name(target.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    had_previous = target.exists()
    if had_previous:
        os.replace(target, backup)
    try:
        os.replace(staged, target)
    except Exception:
        if had_previous and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    else:
        shutil.rmtree(backup, ignore_errors=True)


def approval_payload(
    runtime_dir: Path,
    hashes: dict[str, str],
    auth_report: dict[str, Any],
    malware_scan: dict[str, Any],
    firewall: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": 2,
        "approved": True,
        "approved_by_user": True,
        "approved_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_dir": "runtime/dlss5-v3",
        "source": "Merserk/dlss5-visual-enhancer DLSS 5 Visual Enhancer v3.0",
        "source_url": RELEASE_PAGE,
        "artifact_url": RELEASE_URL,
        "archive_size_bytes": ARCHIVE_SIZE_BYTES,
        "archive_sha256": ARCHIVE_SHA256,
        "authenticode": auth_report,
        "malware_scan": malware_scan,
        "firewall": firewall,
        "experimental": True,
    }
    for filename, key in APPROVAL_HASH_KEYS.items():
        payload[key] = hashes[filename]
    return payload


def write_approval(payload: dict[str, Any]) -> Path:
    APPROVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = APPROVAL_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, APPROVAL_PATH)
    return APPROVAL_PATH


def run_selftest() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.backends.dlss5_selftest"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"DLSS5 Feature-18 self-test failed with exit code {result.returncode}")


def provision(*, archive: Path | None = None, run_hardware_selftest: bool = True) -> Path:
    if os.name != "nt":
        raise RuntimeError("DLSS5 v3 provisioning is supported only on Windows")

    runtime_root = ROOT / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nve-dlss5-v3-", dir=runtime_root) as temporary:
        workspace = Path(temporary)
        owned_archive = archive is None
        archive_path = archive.resolve() if archive else workspace / "DLSS.5.Visual.Enhancer.v3.0.zip"
        if owned_archive:
            download_archive(archive_path)
        else:
            verify_archive(archive_path)

        staged = workspace / "payload"
        hashes = extract_verified_runtime(archive_path, staged)
        auth_report = authenticode_report(staged)
        malware_scan = defender_scan(staged)

        # Activate only after archive, per-file, Authenticode-inspection, and malware
        # scan gates all complete. Approval is intentionally written later.
        activate_runtime(staged)
        firewall = install_firewall_block(RUNTIME_DIR / "nvngx.dll")
        payload = approval_payload(RUNTIME_DIR, hashes, auth_report, malware_scan, firewall)
        write_approval(payload)

    if run_hardware_selftest:
        run_selftest()
    return RUNTIME_DIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        help="Use an existing exact v3.0 release ZIP instead of downloading it.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the experimental runtime/licensing/security notice non-interactively.",
    )
    parser.add_argument(
        "--skip-selftest",
        action="store_true",
        help="Stage and approve the exact runtime without running the hardware Feature-18 self-test.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(NOTICE)
    if not args.yes:
        answer = input("Provision and approve this experimental DLSS5 v3 runtime? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("DLSS5 v3 provisioning skipped.")
            return 0
    try:
        destination = provision(archive=args.archive, run_hardware_selftest=not args.skip_selftest)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        print(f"DLSS5 v3 provisioning failed: {exc}", file=sys.stderr)
        return 1
    print(f"DLSS5 v3 managed runtime ready at {destination}")
    if args.skip_selftest:
        print("Runtime approved, but the backend remains unavailable until the Feature-18 self-test passes.")
    else:
        print("DLSS5 v3 Feature-18 self-test passed; backend should report EXPERIMENTAL READY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
