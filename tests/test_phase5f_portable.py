from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_launcher_prefers_portable_and_supports_source_conda():
    source = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "set \"NVE_FFMPEG_PATH=%~dp0runtime\\tools\\ffmpeg\\ffmpeg.exe\"" in source
    assert "check_portable_runtime.py" in source
    assert '--root "%~dp0."' in source
    assert ":source_mode" in source
    assert "conda run --no-capture-output" in source
    assert "config\\source_env.bat" in source
    assert "where ffmpeg" in source


def test_developer_launcher_keeps_conda_workflow_separate():
    source = (ROOT / "start-dev.bat").read_text(encoding="utf-8")
    assert "conda run" in source


def test_toolchain_metadata_pins_providers():
    import json
    metadata = json.loads((ROOT / "tools" / "portable_toolchain.json").read_text(encoding="utf-8"))
    assert metadata["python"]["sha256"] == "4BA90A4AB8990891033D37FF04D2047FDAE8948D0D2729A68D3A6A17C585B681"
    assert metadata["ffmpeg"]["files"]["ffmpeg.exe"]["size_bytes"] > 0


def test_repair_script_is_fail_closed():
    source = (ROOT / "tools" / "repair_portable.ps1").read_text(encoding="utf-8")
    assert "https://*" in source
    assert "Portable runtime requires repair" in source
    repair = (ROOT / "repair.bat").read_text(encoding="utf-8")
    assert '-Root "%~dp0."' in repair


def test_startup_check_does_not_request_full_hash_scan():
    source = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "--full" not in source


def test_builder_excludes_generated_bytecode_from_runtime_manifest():
    source = (ROOT / "tools" / "build_portable_candidate.py").read_text(encoding="utf-8")
    assert 'ignore_patterns("__pycache__", "*.pyc")' in source
