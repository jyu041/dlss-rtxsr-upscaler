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
    assert {item["layer"] for item in report["checks"]} == {"SYSTEM", "VCRUNTIME", "FFMPEG", "FFPROBE", "PROJECT", "COMMUNITY", "OFFICIAL"}
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


def test_verified_worker_runs_bounded_selftest_and_official_is_not_overstated(monkeypatch, tmp_path):
    worker = tmp_path / "worker.exe"; worker.write_bytes(b"worker")
    official = tmp_path / "official"; official.mkdir(); (official / "opaque.bin").write_bytes(b"runtime")
    monkeypatch.setattr(readiness, "EXPECTED_WORKER_SHA256", readiness.sha256_file(worker))
    monkeypatch.setattr(readiness, "ROOT", tmp_path)
    monkeypatch.setattr(readiness.platform, "system", lambda: "Linux")
    monkeypatch.setattr(readiness.shutil, "which", lambda name: None)
    calls = []
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""
    monkeypatch.setattr(readiness.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or Result())
    report = readiness.assess(worker=worker, official_runtime_dir=official)
    project = next(item for item in report["checks"] if item["layer"] == "PROJECT")
    official_check = next(item for item in report["checks"] if item["layer"] == "OFFICIAL")
    assert project["ok"] and "self-test PASS" in project["detail"]
    assert official_check["state"] == "CONFIGURED / UNVALIDATED" and not official_check["ok"]
    assert any(args[0][1] == "--selftest" and kwargs["timeout"] == 10 for args, kwargs in calls)


def test_worker_selftest_is_not_run_after_hash_mismatch(monkeypatch, tmp_path):
    worker = tmp_path / "worker.exe"; worker.write_bytes(b"wrong")
    monkeypatch.setattr(readiness.shutil, "which", lambda name: None)
    def fail_if_called(*args, **kwargs):
        raise AssertionError("self-test must not run for a mismatched worker")
    monkeypatch.setattr(readiness.subprocess, "run", fail_if_called)
    report = readiness.assess(worker=worker)
    assert next(item for item in report["checks"] if item["layer"] == "PROJECT")["state"] == "IDENTITY MISMATCH"
