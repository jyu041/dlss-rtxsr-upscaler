import json
from pathlib import Path

from src.runtime_manager import RuntimeManager


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "src" / "runtime_manager" / "manifest.json"
BETA2_SHA256 = "F32F8D9586D3A3006D5E26549D9BAB74DD33E10326157D5AEE4620C9DD0006C8"
C55_SHA256 = "C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916"
SR_HOST_SHA256 = "E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB"
SR_RUNTIME_SHA256 = "3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983"


def test_public_release_bootstrap_manifest_is_exact_and_public():
    manager = RuntimeManager(MANIFEST, ROOT / "runtime")
    c55 = manager.specs["project-c55-worker-beta2"]
    sr = manager.specs["project-dlss-sr-beta2"]

    for spec in (c55, sr):
        assert spec.policy == "UPSTREAM_DOWNLOAD"
        assert spec.direct_user_download is True
        assert spec.redistributable is True
        assert spec.sha256 == BETA2_SHA256
        assert spec.artifact_url and "jyu041/dlss-rtxsr-upscaler/releases/download/v0.1.0-beta.2" in spec.artifact_url
        assert "dlss-rtxsr-upscaler-resources" not in spec.artifact_url

    assert c55.destination == "dlssg/worker"
    assert c55.extract_map[-1][1] == "dlssg_sm86_offline.exe"
    assert c55.constraints["worker_sha256"] == C55_SHA256

    assert sr.destination == "dlss-sr-host"
    assert dict(sr.extract_map)[sr.archive_members[0]] == "dlss_sr_host.exe"
    assert dict(sr.extract_map)[sr.archive_members[1]] == "nvngx_dlss.dll"
    assert sr.constraints["host_sha256"] == SR_HOST_SHA256
    assert sr.constraints["runtime_sha256"] == SR_RUNTIME_SHA256


def test_setup_bootstraps_public_resources_and_persists_worker_path():
    setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    assert "project-c55-worker-beta2" in setup
    assert "project-dlss-sr-beta2" in setup
    assert "tools\\manage_runtime.py install" in setup
    assert "runtime\\dlssg\\worker\\dlssg_sm86_offline.exe" in setup
    assert "DLSSG_WORKER_EXE" in setup
    assert "dlss-rtxsr-upscaler-resources" not in setup


def test_manifest_json_has_no_private_bootstrap_dependency():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    serialized = json.dumps(data)
    assert "dlss-rtxsr-upscaler-resources" not in serialized
