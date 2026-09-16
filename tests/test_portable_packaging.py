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
