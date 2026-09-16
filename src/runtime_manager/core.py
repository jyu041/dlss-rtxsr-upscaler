from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable


class RuntimeState(StrEnum):
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED = "INSTALLED"
    UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class RuntimeFile:
    path: str
    url: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class RuntimeSpec:
    id: str
    name: str
    backend: str
    version: str
    source: str
    source_url: str
    artifact_url: str | None
    sha256: str | None
    size_bytes: int | None
    archive_type: str
    allowlist: tuple[str, ...]
    destination: str
    policy: str
    required: bool = False
    constraints: dict[str, object] = field(default_factory=dict)
    notice_url: str | None = None
    channel: str = "candidate"
    license_name: str | None = None
    redistributable: bool = False
    direct_user_download: bool = False
    files: tuple[RuntimeFile, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> "RuntimeSpec":
        required = ("id", "name", "backend", "version", "source", "source_url", "archive_type", "allowlist", "destination", "policy")
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"Runtime manifest missing fields: {', '.join(missing)}")
        source_url = str(data["source_url"])
        artifact_url = data.get("artifact_url")
        for label, url in (("source_url", source_url), ("artifact_url", artifact_url)):
            if url is not None and not str(url).startswith("https://"):
                raise ValueError(f"{label} must use HTTPS")
        allowlist = tuple(str(path) for path in data["allowlist"])
        if not allowlist or any(not _safe_relative_path(path) for path in allowlist):
            raise ValueError("allowlist must contain safe relative paths")
        if len(set(allowlist)) != len(allowlist):
            raise ValueError("allowlist contains duplicate paths")
        destination = str(data["destination"])
        if not _safe_relative_path(destination):
            raise ValueError("destination must be a safe relative path")
        policy = str(data["policy"])
        if policy not in {"PROJECT_BUNDLED", "UPSTREAM_DOWNLOAD", "USER_SUPPLIED", "SYSTEM_COMPONENT"}:
            raise ValueError(f"unknown runtime policy: {policy}")
        file_specs = []
        for item in data.get("files", []):
            if not isinstance(item, dict):
                raise ValueError("runtime files must be objects")
            file_path = str(item.get("path", "")); file_url = str(item.get("url", "")); file_hash = str(item.get("sha256", ""))
            file_size = item.get("size_bytes")
            if not _safe_relative_path(file_path) or not file_url.startswith("https://") or len(file_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in file_hash) or not isinstance(file_size, int) or file_size < 0:
                raise ValueError("runtime file metadata is invalid")
            file_specs.append(RuntimeFile(file_path, file_url, file_hash.upper(), file_size))
        size = data.get("size_bytes")
        if size is not None and (not isinstance(size, int) or size < 0):
            raise ValueError("size_bytes must be a non-negative integer")
        digest = data.get("sha256")
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest)):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        return cls(id=str(data["id"]), name=str(data["name"]), backend=str(data["backend"]), version=str(data["version"]), source=source_url, source_url=source_url, artifact_url=str(artifact_url) if artifact_url is not None else None, sha256=digest.upper() if digest else None, size_bytes=size, archive_type=str(data["archive_type"]), allowlist=allowlist, destination=destination, policy=policy, required=bool(data.get("required", False)), constraints=dict(data.get("constraints", {})), notice_url=str(data["notice_url"]) if data.get("notice_url") else None, channel=str(data.get("channel", "candidate")), license_name=str(data["license_name"]) if data.get("license_name") else None, redistributable=bool(data.get("redistributable", False)), direct_user_download=bool(data.get("direct_user_download", False)), files=tuple(file_specs))


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    return value not in {"", "."} and not path.is_absolute() and ".." not in path.parts and not any(part.endswith(":") for part in path.parts)


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def verify_artifact(path: Path, spec: RuntimeSpec) -> None:
    if spec.size_bytes is not None and path.stat().st_size != spec.size_bytes:
        raise ValueError(f"Artifact size mismatch: {path.stat().st_size} != {spec.size_bytes}")
    if spec.sha256 is not None:
        actual = sha256_file(path)
        if actual != spec.sha256:
            raise ValueError(f"Artifact SHA-256 mismatch: {actual} != {spec.sha256}")


def safe_zip_members(archive: Path, allowlist: Iterable[str]) -> list[str]:
    allowed = {str(PurePosixPath(path.replace("\\", "/"))) for path in allowlist}
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            name = info.filename.replace("\\", "/")
            normalized = str(PurePosixPath(name))
            if info.is_dir():
                continue
            if not _safe_relative_path(name) or normalized in seen:
                raise ValueError(f"Unsafe or duplicate archive member: {name}")
            if normalized not in allowed:
                raise ValueError(f"Unexpected archive member: {name}")
            seen.add(normalized)
    missing = allowed - seen
    if missing:
        raise ValueError(f"Archive is missing required members: {', '.join(sorted(missing))}")
    return sorted(seen)


def extract_safe_zip(archive: Path, staging: Path, allowlist: Iterable[str]) -> None:
    members = safe_zip_members(archive, allowlist)
    staging.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as handle:
        for member in members:
            target = staging / Path(member)
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)


class RuntimeManager:
    """Explicit runtime lifecycle; UI code should call these methods directly."""

    def __init__(self, manifest: Path, install_root: Path, state_path: Path | None = None):
        self.manifest_path = Path(manifest)
        self.install_root = Path(install_root)
        self.state_path = Path(state_path) if state_path else self.install_root / "installed.json"
        self.specs = self._load_manifest()

    def _load_manifest(self) -> dict[str, RuntimeSpec]:
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        entries = data.get("runtimes") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise ValueError("Runtime manifest must contain a runtimes list")
        specs = {spec.id: spec for spec in (RuntimeSpec.from_dict(item) for item in entries)}
        if len(specs) != len(entries):
            raise ValueError("Runtime manifest contains duplicate ids")
        return specs

    def state(self) -> dict[str, dict]:
        if not self.state_path.is_file():
            return {}
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def inspect(self, runtime_id: str) -> tuple[RuntimeSpec, RuntimeState]:
        spec = self.specs[runtime_id]
        record = self.state().get(runtime_id)
        destination = self.install_root / spec.destination
        if not record or not destination.is_dir():
            return spec, RuntimeState.NOT_INSTALLED
        if record.get("version") != spec.version:
            return spec, RuntimeState.UPDATE_AVAILABLE
        return spec, RuntimeState.INSTALLED

    def inventory(self) -> list[dict[str, object]]:
        """Return display-safe lifecycle data without mutating installed runtimes."""
        items = []
        for runtime_id in sorted(self.specs):
            spec, state = self.inspect(runtime_id)
            items.append({
                "id": spec.id,
                "name": spec.name,
                "backend": spec.backend,
                "version": spec.version,
                "state": state.value,
                "policy": spec.policy,
                "channel": spec.channel,
                "license_name": spec.license_name,
                "redistributable": spec.redistributable,
                "direct_user_download": spec.direct_user_download,
                "action": "INSTALL" if spec.policy == "UPSTREAM_DOWNLOAD" else "CONFIGURE",
                "source": spec.source_url,
            })
        return items

    def verify(self, runtime_id: str, selftest: Callable[[Path], None] | None = None) -> dict[str, object]:
        """Verify managed state and optionally run the component's explicit self-test."""
        spec, state = self.inspect(runtime_id)
        destination = (self.install_root / spec.destination).resolve()
        result: dict[str, object] = {"id": spec.id, "state": state.value, "version": spec.version, "destination": str(destination)}
        if state != RuntimeState.INSTALLED:
            result["ok"] = False
            result["detail"] = f"runtime is {state.value}"
            return result
        if selftest:
            selftest(destination)
        result["ok"] = True
        result["detail"] = "managed files present and self-test passed" if selftest else "managed files present; self-test not requested"
        return result

    def download(self, runtime_id: str, target: Path, progress: Callable[[int, int | None], None] | None = None) -> Path:
        spec = self.specs[runtime_id]
        if spec.policy != "UPSTREAM_DOWNLOAD" or not spec.artifact_url:
            raise ValueError("Runtime is not an explicit upstream-download component")
        if not spec.artifact_url.startswith("https://"):
            raise ValueError("Runtime downloads require HTTPS")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{spec.id}-", suffix=".download", dir=target.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        request = urllib.request.Request(spec.artifact_url, headers={"User-Agent": "NVIDIA-Video-Enhancer-runtime-manager"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                total = int(response.headers.get("Content-Length", "0")) or None
                copied = 0
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    copied += len(block)
                    if progress:
                        progress(copied, total)
            verify_artifact(temporary, spec)
            os.replace(temporary, target)
            return target
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def install_files(self, runtime_id: str, *, progress: Callable[[int, int | None], None] | None = None, selftest: Callable[[Path], None] | None = None) -> Path:
        """Explicitly download and activate a pinned multi-file runtime candidate."""
        spec = self.specs[runtime_id]
        if spec.policy != "UPSTREAM_DOWNLOAD" or not spec.files:
            raise ValueError("Runtime does not define pinned upstream files")
        self.install_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{spec.id}-", dir=self.install_root) as temporary:
            downloaded = Path(temporary) / "downloaded"
            downloaded.mkdir()
            total = sum(item.size_bytes for item in spec.files)
            copied_total = 0
            for item in spec.files:
                target = downloaded / item.path
                target.parent.mkdir(parents=True, exist_ok=True)
                request = urllib.request.Request(item.url, headers={"User-Agent": "NVIDIA-Video-Enhancer-runtime-manager"})
                with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as output:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        copied_total += len(block)
                        if progress:
                            progress(copied_total, total)
                if target.stat().st_size != item.size_bytes or sha256_file(target) != item.sha256:
                    raise ValueError(f"Runtime file verification failed: {item.path}")
            return self._activate_directory(runtime_id, downloaded, selftest=selftest)

    def activate_zip(self, runtime_id: str, archive: Path, *, verified: bool = False, selftest: Callable[[Path], None] | None = None) -> Path:
        spec = self.specs[runtime_id]
        if not verified:
            verify_artifact(Path(archive), spec)
        self.install_root.mkdir(parents=True, exist_ok=True)
        staging_parent = Path(tempfile.mkdtemp(prefix=f"{spec.id}-", dir=self.install_root))
        staging = staging_parent / "payload"
        try:
            extract_safe_zip(Path(archive), staging, spec.allowlist)
            return self._activate_directory(runtime_id, staging, selftest=selftest, staging_parent=staging_parent)
        except Exception:
            shutil.rmtree(staging_parent, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging_parent, ignore_errors=True)

    def _activate_directory(self, runtime_id: str, staging: Path, *, selftest: Callable[[Path], None] | None = None, staging_parent: Path | None = None) -> Path:
        spec = self.specs[runtime_id]
        owned_parent = staging_parent is None
        if owned_parent:
            staging_parent = Path(tempfile.mkdtemp(prefix=f"{spec.id}-", dir=self.install_root))
            managed_staging = staging_parent / "payload"
            shutil.copytree(staging, managed_staging)
            staging = managed_staging
        try:
            destination = self.install_root / spec.destination
            backup = destination.with_name(destination.name + ".previous")
            if backup.exists():
                shutil.rmtree(backup)
            had_previous = destination.exists()
            if had_previous:
                os.replace(destination, backup)
            try:
                os.replace(staging, destination)
                if selftest:
                    selftest(destination)
                records = self.state()
                records[spec.id] = {"version": spec.version, "sha256": spec.sha256, "destination": spec.destination}
                temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
                temporary.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
                os.replace(temporary, self.state_path)
                return destination
            except Exception:
                if destination.exists():
                    shutil.rmtree(destination)
                if had_previous and backup.exists():
                    os.replace(backup, destination)
                raise
        except Exception:
            raise
        finally:
            if owned_parent:
                shutil.rmtree(staging_parent, ignore_errors=True)

    def import_zip(self, runtime_id: str, archive: Path) -> Path:
        """Import an offline archive through the same hash and allowlist gates."""
        return self.activate_zip(runtime_id, archive)

    def remove(self, runtime_id: str) -> None:
        spec = self.specs[runtime_id]
        destination = (self.install_root / spec.destination).resolve()
        root = self.install_root.resolve()
        if root not in destination.parents:
            raise ValueError("Runtime destination escapes the managed install root")
        record = self.state().get(runtime_id)
        if record and destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        records = self.state()
        records.pop(runtime_id, None)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)
