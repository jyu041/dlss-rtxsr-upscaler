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


def test_sm86_033_is_not_executable_without_exact_identity_gate():
    # 0.3.3 is the preferred research successor, but no executable profile is
    # allowed until exact runtime identity and the C55 direct-host contract are
    # established.
    assert "candidate-0.3.3" not in PROFILES


def test_dlss5_v10_candidate_is_static_only_and_not_v3_destination():
    manager = RuntimeManager(MANIFEST, ROOT / "runtime")
    candidate = manager.specs["dlss5-neuroframe-v10-static-candidate"]
    assert candidate.channel == "candidate-static-only"
    assert candidate.constraints["static_only"] is True
    assert candidate.destination != "dlss5-v3"


def test_setup_keeps_validated_mfg_and_dlss5_v3_paths():
    setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    assert "DLSSG_RUNTIME_PROFILE=legacy" in setup
    assert "validate_dlssg_candidate.py --profile legacy" in setup
    assert "provision_dlss5_v3.py" in setup
    assert "dlss5-neuroframe-v10-static-candidate" not in setup


def test_startup_does_not_activate_research_candidates():
    start = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "candidate-0.3.3" not in start
    assert "neuroframe-v10" not in start
