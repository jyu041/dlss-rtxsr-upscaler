import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".bat", ".cmd", ".cpp", ".h", ".hpp", ".ini", ".json", ".md",
    ".ps1", ".py", ".txt", ".yml", ".yaml",
}


def _tracked_text_files():
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        path = ROOT / relative
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield relative, path


def test_public_tree_has_no_developer_machine_or_private_resource_identity():
    developer_profile = "C:\\Users\\" + "mark"
    legacy_private_repo = "dlss-rtxsr-upscaler-" + "resources"
    offenders = []
    for relative, path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if developer_profile in text or legacy_private_repo in text:
            offenders.append(relative)
    assert offenders == []


def test_end_user_requirements_exclude_test_and_audit_tooling():
    root_requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    runtime_requirements = (ROOT / "tools" / "requirements" / "runtime.txt").read_text(
        encoding="utf-8"
    )
    test_requirements = (ROOT / "tools" / "requirements" / "test.txt").read_text(
        encoding="utf-8"
    )
    dev_requirements = (ROOT / "tools" / "requirements" / "dev.txt").read_text(
        encoding="utf-8"
    )

    assert "-r tools/requirements/runtime.txt" in root_requirements
    assert "pytest==" not in root_requirements
    assert "pip-audit==" not in root_requirements
    assert "pytest==" not in runtime_requirements
    assert "pip-audit==" not in runtime_requirements
    assert "pytest==" in test_requirements
    assert "pip-audit==" in dev_requirements


def test_root_repair_targets_supported_source_install_by_default():
    repair = (ROOT / "repair.bat").read_text(encoding="utf-8")
    assert 'call "%~dp0setup.bat"' in repair
    assert "runtime\\python\\python.exe" in repair
    assert "tools\\repair_portable.ps1" in repair


def test_fresh_source_install_tracks_runtime_requirements_and_submodule_gitlink():
    workflow = (
        ROOT / ".github" / "workflows" / "fresh-source-install.yml"
    ).read_text(encoding="utf-8")
    assert workflow.count('"tools/requirements/runtime.txt"') == 2
    assert workflow.count('"third_party/ComfyUI-DLSS5-Enhancer"') == 2
