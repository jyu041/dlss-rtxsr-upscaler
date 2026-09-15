import hashlib
import json

from src.core import dlssg_readiness as readiness


def _file(path, content):
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest().upper()


def test_missing_layers_are_explicit_and_nonzero_model(monkeypatch, tmp_path):
    monkeypatch.setattr(readiness, "ROOT", tmp_path)
    monkeypatch.setattr(readiness.platform, "system", lambda: "Windows")
    monkeypatch.setattr(readiness.shutil, "which", lambda name: None)
    report = readiness.assess()
    assert report["state"] == "DLSS-G NOT READY"
    assert {item["layer"] for item in report["checks"]} == {"SYSTEM", "PROJECT", "COMMUNITY", "OFFICIAL"}
    assert all("private" not in json.dumps(item).lower() for item in report["checks"])


def test_worker_and_community_identity_mismatch_are_blocking(monkeypatch, tmp_path):
    worker = tmp_path / "worker.exe"; community = tmp_path / "version.dll"; official = tmp_path / "official"; official.mkdir()
    _file(worker, b"wrong-worker"); _file(community, b"wrong-community")
    monkeypatch.setattr(readiness, "ROOT", tmp_path)
    monkeypatch.setattr(readiness.platform, "system", lambda: "Linux")
    monkeypatch.setattr(readiness.shutil, "which", lambda name: None)
    report = readiness.assess(worker=worker, community_runtime=community, official_runtime_dir=official)
    states = {item["layer"]: item["state"] for item in report["checks"]}
    assert states["PROJECT"] == "IDENTITY MISMATCH"
    assert states["COMMUNITY"] == "IDENTITY MISMATCH"


def test_saved_paths_precede_environment_and_no_fallback(monkeypatch, tmp_path):
    saved = tmp_path / "saved.dll"; env = tmp_path / "env.dll"; official = tmp_path / "official"; official.mkdir()
    _file(saved, b"saved"); _file(env, b"env")
    monkeypatch.setattr(readiness, "load_last_used", lambda: {"dlssg": {"community_runtime": str(saved), "official_runtime_dir": str(official)}})
    monkeypatch.setenv("DLSSG_COMMUNITY_RUNTIME", str(env))
    report = readiness.assess()
    community = next(item for item in report["checks"] if item["layer"] == "COMMUNITY")
    assert "saved.dll" in community["detail"]
    assert "env.dll" not in community["detail"]
