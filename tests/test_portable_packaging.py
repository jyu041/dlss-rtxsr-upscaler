import json
import subprocess
import sys
import zipfile
from pathlib import Path


def test_builder_emits_manifest_checksums_and_deterministic_archive(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("clean source\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Portable Test"], cwd=source, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
    output = tmp_path / "candidate.zip"
    script = Path("tools/build_portable_candidate.py").resolve()
    command = [sys.executable, str(script), "--output", str(output), "--source-root", str(source)]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    digest = output.read_bytes()
    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stderr
    assert output.read_bytes() == digest
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("NVIDIA-Video-Enhancer/build-manifest.json"))
        assert "NVIDIA-Video-Enhancer/SHA256SUMS" in names
        assert len(manifest["source_commit"]) == 40
        assert not any(Path(name).suffix.lower() in {".dll", ".exe", ".pdb", ".lib", ".obj"} for name in names)


def test_builder_stages_only_explicit_external_runtime_inputs(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    (source / "README.md").write_text("clean source\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Portable Test"], cwd=source, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
    python_runtime = tmp_path / "python"; python_runtime.mkdir(); (python_runtime / "python.exe").write_bytes(b"python")
    ffmpeg_runtime = tmp_path / "ffmpeg"; ffmpeg_runtime.mkdir(); (ffmpeg_runtime / "ffmpeg.exe").write_bytes(b"ffmpeg"); (ffmpeg_runtime / "ffprobe.exe").write_bytes(b"ffprobe")
    output = tmp_path / "portable.zip"
    python_notice = tmp_path / "python-notice.txt"; python_notice.write_text("Python terms\n", encoding="utf-8")
    ffmpeg_notice = tmp_path / "ffmpeg-notice.txt"; ffmpeg_notice.write_text("FFmpeg terms\n", encoding="utf-8")
    script = Path("tools/build_portable_candidate.py").resolve()
    result = subprocess.run([sys.executable, str(script), "--output", str(output), "--source-root", str(source), "--python-runtime", str(python_runtime), "--ffmpeg-runtime", str(ffmpeg_runtime), "--python-notice", str(python_notice), "--ffmpeg-notice", str(ffmpeg_notice)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(output) as archive:
        assert "NVIDIA-Video-Enhancer/runtime/python/python.exe" in archive.namelist()
        assert "NVIDIA-Video-Enhancer/runtime/tools/ffmpeg/ffprobe.exe" in archive.namelist()
        assert "NVIDIA-Video-Enhancer/licenses/PORTABLE_PYTHON_NOTICE.txt" in archive.namelist()
        assert "NVIDIA-Video-Enhancer/licenses/FFMPEG_NOTICE.txt" in archive.namelist()


def test_builder_rejects_external_runtime_without_notice(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    (source / "README.md").write_text("clean source\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Portable Test"], cwd=source, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
    runtime = tmp_path / "python"; runtime.mkdir(); (runtime / "python.exe").write_bytes(b"python")
    result = subprocess.run([sys.executable, str(Path("tools/build_portable_candidate.py").resolve()), "--output", str(tmp_path / "candidate.zip"), "--source-root", str(source), "--python-runtime", str(runtime)], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "requires an explicit license notice" in result.stderr
