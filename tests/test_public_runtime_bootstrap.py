import json
from pathlib import Path

from src.runtime_manager import RuntimeManager


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "src" / "runtime_manager" / "manifest.json"
BETA2_SHA256 = "F32F8D9586D3A3006D5E26549D9BAB74DD33E10326157D5AEE4620C9DD0006C8"
LEGACY_PRIVATE_REPO = "dlss-rtxsr-upscaler-" + "resources"
C55_SHA256 = "C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916"
GRID4_ARCHIVE_SHA256 = "5A6644CC78EFEFB3705C80E7859D53C0E75081AAAE33C676D0DC451BE74B80C9"
GRID4_ARCHIVE_SIZE = 209_002
GRID4_WORKER_SHA256 = "E097BC87558D6E12ECE1963E67CD7330570BCFBF6C6ED336B10F1EF6DF2A5881"
GRID4_WORKER_SIZE = 613_376
SR_HOST_SHA256 = "E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB"
SR_RUNTIME_SHA256 = "3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983"
LEGACY_DLSSG_SHA256 = "C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2"
LEGACY_DLSSG_INI_SHA256 = "FD7F0722194E6E8D8C085327D9826EFFB411925A69A5E7549D70EFF26A9F18B5"


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
        assert LEGACY_PRIVATE_REPO not in spec.artifact_url

    assert c55.destination == "dlssg/worker"
    assert c55.extract_map[-1][1] == "dlssg_sm86_offline.exe"
    assert c55.constraints["worker_sha256"] == C55_SHA256

    assert sr.destination == "dlss-sr-host"
    assert dict(sr.extract_map)[sr.archive_members[0]] == "dlss_sr_host.exe"
    assert dict(sr.extract_map)[sr.archive_members[1]] == "nvngx_dlss.dll"
    assert sr.constraints["host_sha256"] == SR_HOST_SHA256
    assert sr.constraints["runtime_sha256"] == SR_RUNTIME_SHA256



def test_public_grid4_worker_manifest_is_exact_and_public():
    manager = RuntimeManager(MANIFEST, ROOT / "runtime")
    grid4 = manager.specs["project-grid4-worker-v1"]
    assert grid4.policy == "UPSTREAM_DOWNLOAD"
    assert grid4.direct_user_download is True
    assert grid4.redistributable is True
    assert grid4.source_url.endswith("/releases/tag/dlssg-grid4-worker-v1")
    assert grid4.artifact_url and grid4.artifact_url.endswith("/releases/download/dlssg-grid4-worker-v1/dlssg-grid4-worker-candidate.zip")
    assert grid4.sha256 == GRID4_ARCHIVE_SHA256
    assert grid4.size_bytes == GRID4_ARCHIVE_SIZE
    assert grid4.destination == "dlssg/grid4-worker"
    assert grid4.constraints["worker_sha256"] == GRID4_WORKER_SHA256
    assert grid4.constraints["worker_size_bytes"] == GRID4_WORKER_SIZE
    assert grid4.constraints["nvof_profile"] == "grid4-gpu-candidate"
    assert grid4.constraints["output_grid"] == 4
    assert grid4.constraints["replaces_c55_default"] is False
    assert set(grid4.allowlist) == {"BUILD-PROVENANCE.json", "dlssg_sm86_offline.exe", "LICENSE-NVIDIA-RTX-SDK.txt", "THIRD_PARTY_NOTICES.md"}


def test_dlssg_normal_runtime_is_the_validated_legacy_direct_host_pair():
    manager = RuntimeManager(MANIFEST, ROOT / "runtime")
    provider = manager.specs["dlssg-official-provider-310.9.1"]
    legacy = manager.specs["dlssg-legacy-reference"]
    candidate = manager.specs["dlssg-sm86-0.3.1-candidate"]

    assert provider.policy == "UPSTREAM_DOWNLOAD"
    assert provider.direct_user_download is True
    assert provider.destination == "dlssg/official"
    assert provider.artifact_url and "NVIDIA-RTX/Streamline" in provider.artifact_url
    assert provider.constraints["provider_sha256"]

    assert legacy.policy == "UPSTREAM_DOWNLOAD"
    assert legacy.direct_user_download is True
    assert legacy.required is True
    assert legacy.destination == "dlssg/legacy"
    assert legacy.constraints["compatibility_test_required"] is False
    assert legacy.constraints["multipliers"] == [2, 3, 4]
    legacy_files = {item.path: item for item in legacy.files}
    assert legacy_files["version.dll"].sha256 == LEGACY_DLSSG_SHA256
    assert legacy_files["version.dll"].size_bytes == 15_667_520
    assert legacy_files["dlssg_sm86.ini"].sha256 == LEGACY_DLSSG_INI_SHA256
    assert legacy_files["dlssg_sm86.ini"].size_bytes == 581
    assert all("5f62ff44a9c08f9841fa605e7b7160f79ccd2c40" in item.url for item in legacy.files)

    # The newer proxy-generation runtime remains available for explicit
    # experimentation, but setup must not promote it over the validated path.
    assert candidate.policy == "UPSTREAM_DOWNLOAD"
    assert candidate.direct_user_download is True
    assert candidate.destination == "dlssg/candidate-0.3.1"
    assert candidate.constraints["compatibility_test_required"] is True


def test_setup_bootstraps_validated_dlssg_path_and_persists_canonical_paths():
    setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    for runtime_id in (
        "project-c55-worker-beta2",
        "project-grid4-worker-v1",
        "project-dlss-sr-beta2",
        "dlssg-official-provider-310.9.1",
        "dlssg-legacy-reference",
    ):
        assert runtime_id in setup
    assert "tools\\manage_runtime.py install" in setup
    assert "tools\\validate_dlssg_candidate.py --profile legacy" in setup
    assert "tools\\check_dlss_sr_readiness.py --selftest" in setup
    assert "runtime\\dlssg\\worker\\dlssg_sm86_offline.exe" in setup
    assert "runtime\\dlssg\\grid4-worker\\dlssg_sm86_offline.exe" in setup
    assert "runtime\\dlssg\\legacy\\version.dll" in setup
    assert "runtime\\dlssg\\official" in setup
    assert "NVE_CONDA_EXE" in setup
    assert "where conda" in setup
    assert "%USERPROFILE%\\miniconda3\\condabin\\conda.bat" in setup
    assert 'echo if not defined NVE_CONDA_EXE set "NVE_CONDA_EXE=' in setup
    assert "DLSSG_WORKER_EXE" in setup
    assert "DLSSG_RUNTIME_PROFILE=legacy" in setup
    assert "DLSSG_COMMUNITY_RUNTIME" in setup
    assert "DLSSG_OFFICIAL_RUNTIME_DIR" in setup
    assert "manage_runtime.py install dlssg-sm86-0.3.1-candidate" not in setup
    assert LEGACY_PRIVATE_REPO not in setup


def test_setup_requires_both_h264_and_hevc_nvenc():
    setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    assert 'findstr /r /c:"h264_nvenc" /c:"hevc_nvenc"' not in setup
    assert setup.count('findstr /r /c:"h264_nvenc" >nul') == 1
    assert setup.count('findstr /r /c:"hevc_nvenc" >nul') == 1
    assert "FFmpeg lacks h264_nvenc." in setup
    assert "FFmpeg lacks hevc_nvenc." in setup


def test_start_reuses_setup_conda_executable_and_preserves_shell_overrides():
    start = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert 'if exist "%~dp0config\\source_env.bat" call "%~dp0config\\source_env.bat"' in start
    assert "NVE_CONDA_EXE" in start
    assert 'call "%NVE_CONDA_EXE%" run --no-capture-output' in start
    assert "where conda" in start
    assert "%USERPROFILE%\\miniconda3\\condabin\\conda.bat" in start


def test_setup_offers_simple_preferred_dlss5_v10_provisioning():
    setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    assert "tools\\provision_dlss5_v10.py" in setup
    assert "tools\\provision_dlss5_v3.py" not in setup
    assert "NVE_SETUP_DLSS5" in setup
    assert 'choice /C YN /N /M "Enable DLSS 5 now? [Y/N] "' in setup
    assert "exact pinned v10 runtime" in setup
    assert "Microsoft Defender preflight" in setup


def test_manifest_json_has_no_private_bootstrap_dependency():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    serialized = json.dumps(data)
    assert LEGACY_PRIVATE_REPO not in serialized
