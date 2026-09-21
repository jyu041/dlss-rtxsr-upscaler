from pathlib import Path

from src.backends.dlssg import DEFAULT_RUNTIME_PROFILE
from src.core.dlssg_profiles import PROFILES
from src.runtime_manager.core import RuntimeManager


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "src" / "runtime_manager" / "manifest.json"


def test_validated_mfg_default_is_unchanged():
    assert DEFAULT_RUNTIME_PROFILE == "legacy"
    assert "legacy" in PROFILES
    assert PROFILES["legacy"].compatibility_required is False


def test_sm86_033_proxy_is_not_a_c55_executable_profile():
    # Static upstream review confirms 0.3.3 remains a DllMain/LoadLibrary proxy
    # architecture rather than the standalone direct-host contract owned by C55.
    # It must not become executable merely because it is newer.
    assert "candidate-0.3.3" not in PROFILES


def test_dlss5_v10_candidate_stays_separate_from_v3_and_requires_explicit_app_gate():
    manager = RuntimeManager(MANIFEST, ROOT / "runtime")
    candidate = manager.specs["dlss5-neuroframe-v10-static-candidate"]
    # Runtime Manager keeps the archive on its selective/static channel; the
    # separately gated application path is explicit and never setup-activated.
    assert candidate.channel == "candidate-static-only"
    assert candidate.constraints["static_only"] is True
    assert candidate.constraints["experimental_app_enabled"] is True
    assert candidate.constraints["experimental_app_processing_scales"] == [1.0]
    assert candidate.destination != "dlss5-v3"


def test_setup_keeps_validated_mfg_and_provisions_preferred_dlss5_v10():
    setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    assert "DLSSG_RUNTIME_PROFILE=legacy" in setup
    assert "validate_dlssg_candidate.py --profile legacy" in setup
    assert "provision_dlss5_v10.py" in setup
    assert "provision_dlss5_v3.py" not in setup


def test_startup_does_not_activate_research_candidates():
    start = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "candidate-0.3.3" not in start
    assert "neuroframe-v10" not in start
