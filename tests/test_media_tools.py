from pathlib import Path
import sys

from src.core import process_utils


def test_bundled_ffmpeg_precedes_system_path(tmp_path, monkeypatch):
    bundled = tmp_path / "runtime" / "tools" / "ffmpeg"
    bundled.mkdir(parents=True)
    ffmpeg = bundled / "ffmpeg.exe"
    ffmpeg.write_bytes(b"placeholder")
    monkeypatch.setattr(process_utils, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(process_utils.shutil, "which", lambda name: f"C:/system/{name}.exe")
    assert process_utils.tool("ffmpeg") == str(ffmpeg)


def test_explicit_tool_override_has_priority(tmp_path, monkeypatch):
    override = tmp_path / "custom-ffmpeg.exe"
    override.write_bytes(b"placeholder")
    monkeypatch.setenv("NVE_FFMPEG_PATH", str(override))
    monkeypatch.setattr(process_utils, "PROJECT_ROOT", tmp_path / "missing")
    assert process_utils.tool("ffmpeg") == str(override)


def test_missing_tool_falls_back_to_path(tmp_path, monkeypatch):
    monkeypatch.delenv("NVE_FFMPEG_PATH", raising=False)
    monkeypatch.setattr(process_utils, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(process_utils.shutil, "which", lambda name: f"C:/system/{name}.exe")
    assert process_utils.tool("ffmpeg") == "C:/system/ffmpeg.exe"


def test_process_runner_replaces_invalid_utf8_in_diagnostics():
    result = process_utils.run(
        [sys.executable, "-c", "import os; os.write(1, b'\\x89PNG\\r\\n')"]
    )
    assert result.returncode == 0
    assert result.stdout.startswith("\ufffdPNG")
