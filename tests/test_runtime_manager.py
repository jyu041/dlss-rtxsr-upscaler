import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from src.runtime_manager.core import RuntimeManager, RuntimeSpec, extract_safe_zip, verify_artifact


def spec(**overrides):
    values = {
        "id": "demo", "name": "Demo", "backend": "demo", "version": "1",
        "source": "https://example.invalid/source", "source_url": "https://example.invalid/source",
        "artifact_url": "https://example.invalid/demo.zip", "sha256": None, "size_bytes": None,
        "archive_type": "zip", "allowlist": ("payload.bin",), "destination": "demo", "policy": "UPSTREAM_DOWNLOAD",
    }
    values.update(overrides)
    return RuntimeSpec(**values)


def test_manifest_rejects_non_https_and_unsafe_allowlist():
    with pytest.raises(ValueError, match="HTTPS"):
        RuntimeSpec.from_dict({"id": "x", "name": "x", "backend": "x", "version": "1", "source": "http://x", "source_url": "http://x", "archive_type": "zip", "allowlist": ["x"], "destination": "x", "policy": "UPSTREAM_DOWNLOAD"})
    with pytest.raises(ValueError, match="safe relative"):
        RuntimeSpec.from_dict({**spec(allowlist=("../payload.bin",)).__dict__})
    with pytest.raises(ValueError, match="destination"):
        RuntimeSpec.from_dict({**spec(destination="../outside").__dict__})
    with pytest.raises(ValueError, match="unknown runtime policy"):
        RuntimeSpec.from_dict({**spec(policy="SILENT").__dict__})


def test_artifact_hash_and_size_are_verified(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"verified")
    digest = hashlib.sha256(b"verified").hexdigest().upper()
    verify_artifact(artifact, spec(sha256=digest, size_bytes=8))
    with pytest.raises(ValueError, match="SHA-256"):
        verify_artifact(artifact, spec(sha256="0" * 64))


def test_safe_zip_rejects_traversal_and_unexpected_members(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.bin", b"bad")
    with pytest.raises(ValueError, match="Unsafe"):
        extract_safe_zip(archive, tmp_path / "stage", ("escape.bin",))
    archive = tmp_path / "unexpected.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("other.bin", b"bad")
    with pytest.raises(ValueError, match="Unexpected"):
        extract_safe_zip(archive, tmp_path / "stage2", ("payload.bin",))


def test_safe_zip_extracts_only_complete_allowlist(tmp_path):
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"ok")
    staging = tmp_path / "stage"
    extract_safe_zip(archive, staging, ("payload.bin",))
    assert (staging / "payload.bin").read_bytes() == b"ok"


def test_selective_zip_rejects_case_collisions_and_extracts_only_allowlist(tmp_path):
    archive = tmp_path / "selective.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("A.dll", b"ignored")
        handle.writestr("a.dll", b"collision")
    with pytest.raises(ValueError, match="Unsafe or duplicate"):
        extract_safe_zip(archive, tmp_path / "stage", ("A.dll",), selective=True)

    archive = tmp_path / "selective-safe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"ok")
        handle.writestr("unrelated.txt", b"ignored")
    staging = tmp_path / "stage-safe"
    extract_safe_zip(archive, staging, ("payload.bin",), selective=True)
    assert (staging / "payload.bin").read_bytes() == b"ok"


def test_manager_manifest_and_state_detection(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"runtimes": [spec().__dict__]}), encoding="utf-8")
    manager = RuntimeManager(manifest, tmp_path / "install")
    loaded, state = manager.inspect("demo")
    assert loaded.version == "1"
    assert state.value == "NOT_INSTALLED"


def test_inventory_labels_user_supplied_components_as_configure(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"runtimes": [spec(policy="USER_SUPPLIED").__dict__]}), encoding="utf-8")
    manager = RuntimeManager(manifest, tmp_path / "install")
    item = manager.inventory()[0]
    assert item["state"] == "NOT_INSTALLED"
    assert item["action"] == "CONFIGURE"


def test_import_and_remove_are_manifest_scoped(tmp_path):
    manifest = tmp_path / "manifest.json"
    demo = spec(allowlist=("payload.bin",), policy="USER_SUPPLIED")
    manifest.write_text(json.dumps({"runtimes": [demo.__dict__]}), encoding="utf-8")
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"ok")
    manager = RuntimeManager(manifest, tmp_path / "install")
    destination = manager.import_zip("demo", archive)
    assert (destination / "payload.bin").read_bytes() == b"ok"
    manager.remove("demo")
    assert not destination.exists()
    assert manager.inspect("demo")[1].value == "NOT_INSTALLED"


def test_verify_reports_state_and_runs_optional_selftest(tmp_path):
    manifest = tmp_path / "manifest.json"
    demo = spec(allowlist=("payload.bin",), policy="USER_SUPPLIED")
    manifest.write_text(json.dumps({"runtimes": [demo.__dict__]}), encoding="utf-8")
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"ok")
    manager = RuntimeManager(manifest, tmp_path / "install")
    manager.import_zip("demo", archive)
    called = []
    result = manager.verify("demo", selftest=lambda path: called.append(path))
    assert result["ok"] is True and called


def test_verify_detects_modified_managed_file(tmp_path):
    manifest = tmp_path / "manifest.json"
    demo = spec(allowlist=("payload.bin",), policy="USER_SUPPLIED")
    manifest.write_text(json.dumps({"runtimes": [demo.__dict__]}), encoding="utf-8")
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"ok")
    manager = RuntimeManager(manifest, tmp_path / "install")
    manager.import_zip("demo", archive)
    (tmp_path / "install" / "demo" / "payload.bin").write_bytes(b"tampered")
    result = manager.verify("demo")
    assert result["ok"] is False
    assert "integrity" in result["detail"]


def test_manifest_loads_pinned_multifile_candidate():
    manager = RuntimeManager(Path("src/runtime_manager/manifest.json"), Path("runtime"))
    spec = manager.specs["dlssg-sm86-0.3.1-candidate"]
    assert spec.policy == "UPSTREAM_DOWNLOAD"
    assert [item.path for item in spec.files] == ["version.dll", "dlssg_sm86.ini", "THIRD_PARTY_NOTICES.txt"]
    assert spec.direct_user_download is True and spec.redistributable is False


def test_manifest_loads_exact_official_provider_extraction_policy():
    manager = RuntimeManager(Path("src/runtime_manager/manifest.json"), Path("runtime"))
    provider = manager.specs["dlssg-official-provider-310.9.1"]
    assert provider.sha256 == "92C4D954631A1710DA86CA3FA8D5034F2B9503838C95FC4AE977AE149319781B"
    assert provider.archive_members == ("bin/x64/nvngx_dlssg.dll", "bin/x64/nvngx_dlss.license.txt")
    assert provider.extract_map[0] == ("bin/x64/nvngx_dlssg.dll", "nvngx_dlssg.dll")


def test_inventory_exposes_expected_and_current_identity(tmp_path):
    manifest = tmp_path / "manifest.json"
    demo = spec(policy="USER_SUPPLIED")
    manifest.write_text(json.dumps({"runtimes": [demo.__dict__]}), encoding="utf-8")
    manager = RuntimeManager(manifest, tmp_path / "install")
    item = manager.inventory()[0]
    assert item["current_version"] is None and item["version"] == "1"
    assert item["state"] == "NOT_INSTALLED"


def test_install_dispatches_to_pinned_multifile_flow(tmp_path, monkeypatch):
    manager = RuntimeManager(Path("src/runtime_manager/manifest.json"), tmp_path / "runtime")
    called = []
    monkeypatch.setattr(manager, "install_files", lambda runtime_id, **kwargs: called.append(runtime_id) or tmp_path / "installed")
    assert manager.install("dlssg-sm86-0.3.1-candidate") == tmp_path / "installed"
    assert called == ["dlssg-sm86-0.3.1-candidate"]


def test_repair_reuses_explicit_pinned_install_path(tmp_path, monkeypatch):
    manager = RuntimeManager(Path("src/runtime_manager/manifest.json"), tmp_path / "runtime")
    called = []
    monkeypatch.setattr(manager, "install", lambda runtime_id, **kwargs: called.append((runtime_id, kwargs)) or tmp_path / "repaired")
    result = manager.repair("dlssg-sm86-0.3.1-candidate", selftest=lambda _path: None)
    assert result == tmp_path / "repaired"
    assert called[0][0] == "dlssg-sm86-0.3.1-candidate"
    assert called[0][1]["selftest"] is not None


def test_repair_rejects_user_supplied_runtime(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"runtimes": [spec(policy="USER_SUPPLIED").__dict__]}), encoding="utf-8")
    manager = RuntimeManager(manifest, tmp_path / "install")
    with pytest.raises(ValueError, match="upstream-download"):
        manager.repair("demo")


def test_multifile_install_verifies_each_download_before_activation(tmp_path, monkeypatch):
    first, second = b"first", b"second"
    import hashlib
    files = [
        {"path": "version.dll", "url": "https://example.invalid/version.dll", "sha256": hashlib.sha256(first).hexdigest(), "size_bytes": len(first)},
        {"path": "dlssg_sm86.ini", "url": "https://example.invalid/dlssg_sm86.ini", "sha256": hashlib.sha256(second).hexdigest(), "size_bytes": len(second)},
    ]
    values = {**spec(policy="UPSTREAM_DOWNLOAD").__dict__, "files": files, "artifact_url": None, "allowlist": ("version.dll", "dlssg_sm86.ini")}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"runtimes": [values]}), encoding="utf-8")

    class Response:
        headers = {"Content-Length": "0"}
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self, _size):
            data, self.data = self.data, b""
            return data

    payloads = iter((first, second))
    monkeypatch.setattr("src.runtime_manager.core.urllib.request.urlopen", lambda *_args, **_kwargs: Response(next(payloads)))
    manager = RuntimeManager(manifest, tmp_path / "install")
    destination = manager.install_files("demo")
    assert (destination / "version.dll").read_bytes() == first
    assert (destination / "dlssg_sm86.ini").read_bytes() == second


def test_activation_runs_selftest_before_recording_state_and_rolls_back(tmp_path):
    manifest = tmp_path / "manifest.json"
    demo = spec(allowlist=("payload.bin",), policy="USER_SUPPLIED")
    manifest.write_text(json.dumps({"runtimes": [demo.__dict__]}), encoding="utf-8")
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"new")
    manager = RuntimeManager(manifest, tmp_path / "install")
    manager.import_zip("demo", archive)
    old = (tmp_path / "install" / "demo" / "payload.bin").read_bytes()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"replacement")
    with pytest.raises(RuntimeError, match="self-test"):
        manager.activate_zip("demo", archive, selftest=lambda _path: (_ for _ in ()).throw(RuntimeError("self-test failed")))
    assert (tmp_path / "install" / "demo" / "payload.bin").read_bytes() == old
    assert manager.inspect("demo")[1].value == "INSTALLED"


@pytest.mark.parametrize("member", ["payload.bin:stream", "CON.txt", "payload.bin.", "payload.bin "])
def test_safe_zip_rejects_windows_namespace_hazards(tmp_path, member):
    archive = tmp_path / "hazard.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(member, b"bad")
    with pytest.raises(ValueError, match="Unsafe"):
        extract_safe_zip(archive, tmp_path / "stage", (member,))


def test_candidate_install_is_files_verified_but_validation_required(tmp_path):
    manifest = tmp_path / "manifest.json"
    candidate = spec(constraints={"compatibility_test_required": True})
    manifest.write_text(json.dumps({"runtimes": [candidate.__dict__]}), encoding="utf-8")
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.bin", b"ok")
    manager = RuntimeManager(manifest, tmp_path / "install")
    manager.import_zip("demo", archive)
    assert manager.inspect("demo")[1].value == "VALIDATION_REQUIRED"
    result = manager.verify("demo")
    assert result["ok"] is True and result["files_verified"] is True and result["backend_ready"] is False


def test_manifest_loads_dlss5_v10_static_candidate():
    manager = RuntimeManager(Path("src/runtime_manager/manifest.json"), Path("runtime"))
    candidate = manager.specs["dlss5-neuroframe-v10-static-candidate"]
    assert candidate.version == "v10.0-7781107b"
    assert candidate.sha256 == "394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515"
    assert candidate.size_bytes == 690203043
    assert candidate.channel == "candidate-static-only"
    assert candidate.redistributable is False
    assert candidate.direct_user_download is True
    assert candidate.destination == "dlss5/neuroframe-v10-candidate"
    assert candidate.allowlist == (
        "bin/runtime/dlssnr/nvngx_dlssnr.dll",
        "bin/runtime/dlssnr/neuroframe_engine_neural_rendering.dll",
        "bin/runtime/dlssnr/neuroframe_caller.dll",
        "bin/runtime/dlssnr/LICENSE-NVIDIA-DLSS.txt",
        "bin/runtime/dlssnr/LICENSE-Merserk.txt",
    )
    assert candidate.constraints["static_only"] is True
    assert candidate.constraints["feature_id_observed"] == 18
    assert candidate.constraints["processing_scale_is_lanczos_pre_resize"] is True
    assert candidate.constraints["native_output_scaling_unverified"] is True
    audit = candidate.constraints["static_audit"]
    assert audit["workflow_run_id"] == 35311872691
    assert audit["executed"] is False
    assert audit["all_runtime_dlls_x86_64"] is True
    assert audit["all_runtime_dlls_authenticode"] == "NotSigned"
    assert audit["direct_network_imports_observed"] is False
    assert audit["direct_process_launch_imports_observed"] is False
    files = candidate.constraints["extracted_files"]
    assert files["nvngx_dlssnr.dll"]["sha256"] == "6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927"
    assert files["neuroframe_engine_neural_rendering.dll"]["sha256"] == "F657D20E569F97DEC25E02141F64354CD4B3E1DC51FA1DFE48ACEEBCC3CC43D5"
    assert files["neuroframe_caller.dll"]["sha256"] == "B3611046837BC2F2E957A694CE0817E3C1B304BD653D0C7A193148E5BDD02437"
