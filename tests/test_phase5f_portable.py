from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_launcher_is_portable_only():
    source = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "conda" not in source.lower()
    assert "set \"NVE_FFMPEG_PATH=%~dp0runtime\\tools\\ffmpeg\\ffmpeg.exe\"" in source
    assert "check_portable_runtime.py" in source


def test_developer_launcher_keeps_conda_workflow_separate():
    source = (ROOT / "start-dev.bat").read_text(encoding="utf-8")
    assert "conda run" in source


def test_toolchain_metadata_pins_providers():
    import json
    metadata = json.loads((ROOT / "tools" / "portable_toolchain.json").read_text(encoding="utf-8"))
    assert metadata["python"]["sha256"] == "009D6BF7E3B2DDCA3D784FA09F90FE54336D5B60F0E0F305C37F400BF83CFD3B"
    assert metadata["ffmpeg"]["files"]["ffmpeg.exe"]["size_bytes"] > 0


def test_repair_script_is_fail_closed():
    source = (ROOT / "tools" / "repair_portable.py").read_text(encoding="utf-8")
    assert "never downloads" in source
    assert "incomplete candidate" in source
