from pathlib import Path

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
