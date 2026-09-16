import json
import subprocess
import sys
import zipfile
from pathlib import Path


def test_builder_emits_manifest_checksums_and_deterministic_archive(tmp_path):
    output = tmp_path / "candidate.zip"
    command = [sys.executable, "tools/build_portable_candidate.py", "--output", str(output)]
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
