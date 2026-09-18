"""Audit a static-only runtime candidate without executing any extracted file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime_manager.core import (
    RuntimeManager,
    RuntimeSpec,
    extract_safe_zip,
    sha256_file,
    verify_artifact,
)
from src.core.pe_static import inspect_pe


MANIFEST = ROOT / "src" / "runtime_manager" / "manifest.json"


def _authenticode(path: Path) -> dict[str, object]:
    """Observe Authenticode metadata without loading or executing the file."""
    if os.name != "nt":
        return {
            "tool": None,
            "status": "Unavailable",
            "reason": "Authenticode inspection requires Windows",
        }

    quoted = str(path.resolve()).replace("'", "''")
    script = (
        "$ErrorActionPreference='Stop'; "
        "Import-Module Microsoft.PowerShell.Security -ErrorAction Stop; "
        f"$s=Get-AuthenticodeSignature -LiteralPath '{quoted}' -ErrorAction Stop; "
        "[pscustomobject]@{"
        "status=$s.Status.ToString();"
        "status_message=$s.StatusMessage;"
        "signer_subject=$(if($s.SignerCertificate){$s.SignerCertificate.Subject}else{$null});"
        "signer_thumbprint=$(if($s.SignerCertificate){$s.SignerCertificate.Thumbprint}else{$null})"
        "} | ConvertTo-Json -Compress"
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
        return {
            "tool": "Get-AuthenticodeSignature",
            "status": "InspectionError",
            "exit_code": result.returncode,
            "detail": (result.stderr or result.stdout).strip(),
        }
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        return {
            "tool": "Get-AuthenticodeSignature",
            "status": "InspectionError",
            "detail": f"Invalid JSON output: {exc}",
        }
    return {"tool": "Get-AuthenticodeSignature", **payload}


def audit_static_archive(
    spec: RuntimeSpec,
    archive: Path,
    *,
    include_authenticode: bool = False,
) -> dict[str, object]:
    """Return deterministic identity evidence for one static-only archive."""
    if not spec.constraints.get("static_only"):
        raise ValueError(f"{spec.id} is not marked static_only")
    if spec.archive_type != "selective-zip":
        raise ValueError(
            f"{spec.id} uses unsupported static audit archive type: {spec.archive_type}"
        )

    archive = Path(archive).expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    verify_artifact(archive, spec)

    with tempfile.TemporaryDirectory(prefix=f"nve-audit-{spec.id}-") as temporary:
        staging = Path(temporary) / "payload"
        extract_safe_zip(archive, staging, spec.allowlist, selective=True)

        files: list[dict[str, object]] = []
        for member in spec.allowlist:
            path = staging / Path(member)
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f"Static audit member is missing or invalid: {member}")
            record: dict[str, object] = {
                "path": member,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            if path.suffix.lower() in {".dll", ".exe"}:
                record["pe"] = inspect_pe(path)
            if include_authenticode:
                record["authenticode"] = _authenticode(path)
            files.append(record)

    return {
        "schema": 1,
        "runtime_id": spec.id,
        "name": spec.name,
        "version": spec.version,
        "source_url": spec.source_url,
        "artifact_url": spec.artifact_url,
        "archive": {
            "path": str(archive),
            "size_bytes": archive.stat().st_size,
            "sha256": sha256_file(archive),
        },
        "static_only": True,
        "executed": False,
        "files": files,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_id", help="Manifest runtime id; must be static_only")
    parser.add_argument("--archive", required=True, type=Path, help="Exact candidate ZIP")
    parser.add_argument(
        "--authenticode",
        action="store_true",
        help="Also record Windows Authenticode observations for extracted files",
    )
    parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manager = RuntimeManager(MANIFEST, ROOT / "runtime")
    try:
        spec = manager.specs[args.runtime_id]
    except KeyError:
        print(f"Unknown runtime id: {args.runtime_id}", file=sys.stderr)
        return 2

    try:
        report = audit_static_archive(
            spec,
            args.archive,
            include_authenticode=args.authenticode,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Static candidate audit failed: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(output)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
