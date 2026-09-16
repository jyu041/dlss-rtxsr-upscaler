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


def _https_urlopen(request, timeout: int = 60):
    """Open a pinned URL while refusing HTTPS-to-HTTP downgrade redirects."""
    response = urllib.request.urlopen(request, timeout=timeout)
    final_url = str(response.geturl() if hasattr(response, "geturl") else request.full_url)
    if not final_url.lower().startswith("https://"):
        response.close()
        raise ValueError(f"HTTPS runtime download redirected to non-HTTPS URL: {final_url}")
    return response


class RuntimeState(StrEnum):
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED = "INSTALLED"
    UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
    INVALID = "INVALID"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"
    READY = "READY"
    STATIC_ONLY = "STATIC_ONLY"
    MODIFIED = "MODIFIED"


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
    archive_members: tuple[str, ...] = ()
    extract_map: tuple[tuple[str, str], ...] = ()

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
        archive_members = tuple(str(path) for path in data.get("archive_members", []))
        if archive_members and (len(archive_members) != len(allowlist) or any(not _safe_relative_path(path) for path in archive_members)):
            raise ValueError("archive_members must contain safe relative paths matching the allowlist")
        extract_map = tuple((str(source), str(target)) for source, target in dict(data.get("extract_map", {})).items())
        if extract_map and (set(source for source, _ in extract_map) != set(archive_members) or any(not _safe_relative_path(source) or not _safe_relative_path(target) for source, target in extract_map)):
            raise ValueError("extract_map must map every safe archive member to a safe destination")
        return cls(id=str(data["id"]), name=str(data["name"]), backend=str(data["backend"]), version=str(data["version"]), source=str(data["source"]), source_url=source_url, artifact_url=str(artifact_url) if artifact_url is not None else None, sha256=digest.upper() if digest else None, size_bytes=size, archive_type=str(data["archive_type"]), allowlist=allowlist, destination=destination, policy=policy, required=bool(data.get("required", False)), constraints=dict(data.get("constraints", {})), notice_url=str(data["notice_url"]) if data.get("notice_url") else None, channel=str(data.get("channel", "candidate")), license_name=str(data["license_name"]) if data.get("license_name") else None, redistributable=bool(data.get("redistributable", False)), direct_user_download=bool(data.get("direct_user_download", False)), files=tuple(file_specs), archive_members=archive_members, extract_map=extract_map)


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if value in {"", "."} or path.is_absolute() or ".." in path.parts:
        return False
    for part in path.parts:
        if not part or part.endswith((".", " ")) or ":" in part:
            return False
        if part.split(".", 1)[0].upper() in reserved:
            return False
    return True


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


def safe_zip_members(archive: Path, allowlist: Iterable[str], *, selective: bool = False) -> list[str]:
    allowed = {str(PurePosixPath(path.replace("\\", "/"))) for path in allowlist}
    allowed_folded = {item.casefold() for item in allowed}
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            name = info.filename.replace("\\", "/")
            normalized = str(PurePosixPath(name))
            if info.is_dir():
                continue
            if not _safe_relative_path(name) or normalized.casefold() in {item.casefold() for item in seen}:
                raise ValueError(f"Unsafe or duplicate archive member: {name}")
            if not selective and normalized.casefold() not in allowed_folded:
                raise ValueError(f"Unexpected archive member: {name}")
            seen.add(normalized)
    missing = allowed - seen
    if missing:
        raise ValueError(f"Archive is missing required members: {', '.join(sorted(missing))}")
    return sorted(item for item in seen if not selective or item.casefold() in allowed_folded)


def extract_safe_zip(archive: Path, staging: Path, allowlist: Iterable[str], *, selective: bool = False) -> None:
    members = safe_zip_members(archive, allowlist, selective=selective)
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

    def _candidate_attestation_current(self, destination: Path) -> bool:
        """Derive candidate readiness from files plus the current machine attestation."""
        if not destination.is_dir():
            return False
        try:
            from src.core.dlssg_attestation import current, is_current, load
            from src.core.dlssg_official_runtime import identity
            from src.core.dlssg_profiles import profile
            runtime = destination / "version.dll"
            ini = destination / "dlssg_sm86.ini"
            official = Path(os.environ.get("DLSSG_OFFICIAL_RUNTIME_DIR", str(self.install_root / "dlssg" / "official"))).expanduser().resolve()
            worker = Path(os.environ.get("DLSSG_WORKER_EXE", str(Path(__file__).resolve().parents[2] / "native" / "dlssg_sm86_offline" / "bin" / "dlssg_sm86_offline.exe"))).expanduser().resolve()
            expected = current(runtime_path=runtime, ini_path=ini, official_identity=identity(official), worker_path=worker)
            return bool(load()) and is_current(load() or {}, expected)
        except (OSError, ValueError, TypeError):
            return False

    def inspect(self, runtime_id: str) -> tuple[RuntimeSpec, RuntimeState]:
        spec = self.specs[runtime_id]
        record = self.state().get(runtime_id)
        destination = self.install_root / spec.destination
        if not record and not destination.exists():
            return spec, RuntimeState.NOT_INSTALLED
        if not record or not destination.is_dir():
            return spec, RuntimeState.INVALID
        if record.get("integrity") == "INVALID":
            return spec, RuntimeState.INVALID
        if record.get("version") != spec.version:
            return spec, RuntimeState.UPDATE_AVAILABLE
        if spec.constraints.get("static_only"):
            return spec, RuntimeState.STATIC_ONLY
        if spec.constraints.get("compatibility_test_required"):
            return spec, RuntimeState.READY if self._candidate_attestation_current(destination) else RuntimeState.VALIDATION_REQUIRED
        return spec, RuntimeState.INSTALLED

    def inventory(self) -> list[dict[str, object]]:
        """Return display-safe lifecycle data without mutating installed runtimes."""
        items = []
        for runtime_id in sorted(self.specs):
            spec, state = self.inspect(runtime_id)
            record = self.state().get(runtime_id, {})
            items.append({
                "id": spec.id,
                "name": spec.name,
                "backend": spec.backend,
                "version": spec.version,
                "current_version": record.get("version"),
                "current_sha256": record.get("sha256"),
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
        if state not in (RuntimeState.INSTALLED, RuntimeState.VALIDATION_REQUIRED, RuntimeState.STATIC_ONLY):
            result["ok"] = False
            result["detail"] = f"runtime is {state.value}"
            return result
        try:
            file_records = self._installed_file_records(spec, destination)
            recorded = self.state().get(runtime_id, {}).get("files")
            if not isinstance(recorded, list) or recorded != file_records:
                result["ok"] = False
                result["detail"] = "managed file integrity record is missing or does not match"
                return result
        except (OSError, ValueError) as exc:
            result["ok"] = False
            result["detail"] = f"managed file integrity check failed: {exc}"
            return result
        if spec.constraints.get("compatibility_test_required"):
            ready = self._candidate_attestation_current(destination)
            result["files_verified"] = True
            result["backend_ready"] = ready
            result["ok"] = True
            result["state"] = RuntimeState.READY.value if ready else RuntimeState.VALIDATION_REQUIRED.value
            result["detail"] = "managed files and current compatibility attestation verified" if ready else "managed files verified; current compatibility attestation is required"
            return result
        if selftest is None and not self.specs[runtime_id].constraints.get("compatibility_test_required"):
            selftest = __import__("src.runtime_manager.selftests", fromlist=["selftest_for"]).selftest_for(runtime_id)
        if selftest:
            try:
                selftest(destination)
            except Exception as exc:
                result["ok"] = False
                result["backend_ready"] = False
                result["detail"] = f"files verified; backend self-test failed: {exc}"
                return result
        result["files_verified"] = True
        result["backend_ready"] = not spec.constraints.get("static_only", False)
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
            with _https_urlopen(request, timeout=60) as response, temporary.open("wb") as output:
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

    def install(self, runtime_id: str, *, target: Path | None = None, progress: Callable[[int, int | None], None] | None = None, selftest: Callable[[Path], None] | None = None) -> Path:
        """Perform one explicit installation using only the manifest's pinned source."""
        if selftest is None and self.specs[runtime_id].constraints.get("compatibility_test_required"):
            selftest = None
        else:
            selftest = selftest or __import__("src.runtime_manager.selftests", fromlist=["selftest_for"]).selftest_for(runtime_id)
        spec = self.specs[runtime_id]
        if spec.files:
            return self.install_files(runtime_id, progress=progress, selftest=selftest)
        if not target:
            raise ValueError("an archive target is required for this runtime")
        archive = self.download(runtime_id, target, progress=progress)
        return self.activate_zip(runtime_id, archive, selftest=selftest)

    def repair(self, runtime_id: str, *, target: Path | None = None, progress: Callable[[int, int | None], None] | None = None, selftest: Callable[[Path], None] | None = None) -> Path:
        """Reinstall the pinned runtime after an explicit user request.

        Repair never selects a different source or silently downloads. It uses
        the same manifest-driven path as ``install`` and retains the existing
        activation rollback behavior. The caller supplies an archive target
        for archive-based runtimes; multi-file runtimes stage their downloads
        under the managed root and do not need one.
        """
        selftest = selftest or __import__("src.runtime_manager.selftests", fromlist=["selftest_for"]).selftest_for(runtime_id)
        spec = self.specs[runtime_id]
        if spec.policy != "UPSTREAM_DOWNLOAD":
            raise ValueError("Only explicit upstream-download components can be repaired")
        return self.install(runtime_id, target=target, progress=progress, selftest=selftest)

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
                with _https_urlopen(request, timeout=60) as response, target.open("wb") as output:
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
            extract_safe_zip(Path(archive), staging, spec.archive_members or spec.allowlist, selective=spec.archive_type in {"selective-zip", "provider-zip"})
            for source, target in spec.extract_map:
                source_path = staging / Path(source)
                target_path = staging / Path(target)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source_path, target_path)
            if spec.extract_map:
                for source, _ in spec.extract_map:
                    source_path = staging / Path(source)
                    if source_path.exists():
                        source_path.unlink()
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
            destination.parent.mkdir(parents=True, exist_ok=True)
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
                file_records = self._installed_file_records(spec, destination)
                records = self.state()
                records[spec.id] = {"version": spec.version, "sha256": spec.sha256, "destination": spec.destination, "files": file_records,
                                    "files_verified": True, "backend_ready": bool(selftest) and not spec.constraints.get("static_only", False),
                                    "validation_required": bool(spec.constraints.get("compatibility_test_required", False)) and not bool(selftest)}
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

    def _installed_file_records(self, spec: RuntimeSpec, destination: Path) -> list[dict[str, object]]:
        """Return the exact allowlisted file identities for an active runtime."""
        if not destination.is_dir():
            raise ValueError("runtime destination is not a directory")
        actual: list[dict[str, object]] = []
        for path in destination.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(destination).as_posix()
            actual.append({"path": relative, "sha256": sha256_file(path), "size_bytes": path.stat().st_size})
        actual.sort(key=lambda item: str(item["path"]).casefold())
        expected = sorted((str(PurePosixPath(path.replace("\\", "/"))) for path in spec.allowlist), key=str.casefold)
        names = [str(item["path"]) for item in actual]
        if names != expected:
            raise ValueError(f"managed file set differs from allowlist: {names}")
        return actual

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
