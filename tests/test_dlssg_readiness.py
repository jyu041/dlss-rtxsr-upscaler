import hashlib
import json
import sys

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
    community = tmp_path / "version.dll"; community.write_bytes(b"community")
    official = tmp_path / "official"; official.mkdir(); (official / "opaque.bin").write_bytes(b"runtime")
    monkeypatch.setattr(readiness, "EXPECTED_WORKER_SHA256", readiness.sha256_file(worker))
    monkeypatch.setattr(readiness, "EXPECTED_COMMUNITY_SHA256", readiness.sha256_file(community))
    monkeypatch.setattr(readiness, "ROOT", tmp_path)
    monkeypatch.setattr(readiness.platform, "system", lambda: "Windows")
    system32 = tmp_path / "System32"; system32.mkdir(); (system32 / "nvofapi64.dll").write_bytes(b"nvof")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setattr(readiness.shutil, "which", lambda name: None)
    ready = lambda *args, **kwargs: readiness.ReadinessCheck("TEST", "READY", True, "ready")
    monkeypatch.setattr(readiness, "_gpu_check", ready)
    monkeypatch.setattr(readiness, "_vc_runtime_check", ready)
    monkeypatch.setattr(readiness, "_ffmpeg_check", ready)
    monkeypatch.setattr(readiness, "_ffprobe_check", ready)
    calls = []
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""
    monkeypatch.setattr(readiness.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or Result())
    report = readiness.assess(worker=worker, community_runtime=community, official_runtime_dir=official)
    project = next(item for item in report["checks"] if item["layer"] == "PROJECT")
    official_check = next(item for item in report["checks"] if item["layer"] == "OFFICIAL")
    assert project["ok"] and "self-test PASS" in project["detail"]
    assert official_check["state"] == "CONFIGURED / UNVALIDATED" and official_check["ok"]
    assert report["state"] == "DLSS-G STATICALLY READY"
    assert report["static_ready"] is True and report["ready"] is True
    assert "BLOCKED OFFICIAL" not in readiness.format_summary(report)
    assert "PASS OFFICIAL: configured; native runtime remains dynamically unvalidated" in readiness.format_summary(report)
    assert any(args[0][1] == "--selftest" and kwargs["timeout"] == 10 for args, kwargs in calls)


def test_cli_success_semantics_follow_static_preflight(monkeypatch, capsys):
    from tools import check_dlssg_readiness

    report = {"state": "DLSS-G STATICALLY READY", "ready": True, "static_ready": True, "checks": [], "policy": {}}
    monkeypatch.setattr(check_dlssg_readiness, "assess", lambda **kwargs: report)
    monkeypatch.setattr(sys, "argv", ["check_dlssg_readiness.py"])
    assert check_dlssg_readiness.main() == 0
    assert "DLSS-G STATICALLY READY" in capsys.readouterr().out


def test_cli_missing_dependency_is_nonzero(monkeypatch):
    from tools import check_dlssg_readiness

    report = {"state": "DLSS-G NOT READY", "ready": False, "static_ready": False, "checks": [], "policy": {}}
    monkeypatch.setattr(check_dlssg_readiness, "assess", lambda **kwargs: report)
    monkeypatch.setattr(sys, "argv", ["check_dlssg_readiness.py"])
    assert check_dlssg_readiness.main() == 1


def test_worker_selftest_is_not_run_after_hash_mismatch(monkeypatch, tmp_path):
    worker = tmp_path / "worker.exe"; worker.write_bytes(b"wrong")
    monkeypatch.setattr(readiness.shutil, "which", lambda name: None)
    def fail_if_called(*args, **kwargs):
        raise AssertionError("self-test must not run for a mismatched worker")
    monkeypatch.setattr(readiness.subprocess, "run", fail_if_called)
    report = readiness.assess(worker=worker)
    assert next(item for item in report["checks"] if item["layer"] == "PROJECT")["state"] == "IDENTITY MISMATCH"


class _Result:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = code, stdout, stderr


def test_ffmpeg_encoder_and_ffprobe_failures_are_separate(monkeypatch):
    monkeypatch.setattr(readiness.shutil, "which", lambda name: name)
    def run(args, **kwargs):
        if args[0] == "ffmpeg" and args[-1] == "-encoders":
            return _Result(stdout=" h264_nvenc ")
        if args[0] == "ffmpeg":
            return _Result(stdout="ffmpeg version test")
        return _Result(code=1)
    monkeypatch.setattr(readiness.subprocess, "run", run)
    assert readiness._ffmpeg_check(False).state == "INCOMPLETE"
    assert readiness._ffprobe_check(False).state == "BROKEN"


def test_gpu_query_failure_and_identity_are_actionable(monkeypatch):
    monkeypatch.setattr(readiness.shutil, "which", lambda name: "nvidia-smi")
    monkeypatch.setattr(readiness.subprocess, "run", lambda args, **kwargs: _Result(stdout="NVIDIA GeForce RTX 3070 Ti, 610.62"))
    good = readiness._gpu_check(False)
    assert good.ok and "RTX 3070 Ti" in good.detail and "610.62" in good.detail
    monkeypatch.setattr(readiness.subprocess, "run", lambda args, **kwargs: _Result(code=6))
    bad = readiness._gpu_check(False)
    assert not bad.ok and "query failed" in bad.detail


def test_candidate_profile_selects_only_managed_candidate(monkeypatch):
    monkeypatch.setenv("DLSSG_RUNTIME_PROFILE", "candidate-0.3.1")
    monkeypatch.delenv("DLSSG_COMMUNITY_RUNTIME", raising=False)
    monkeypatch.setattr(readiness, "load_last_used", lambda: {"dlssg": {}})
    selected = readiness._community_runtime(None, None)
    assert selected == (readiness.ROOT / "runtime" / "dlssg" / "candidate-0.3.1" / "version.dll").resolve()


def test_missing_ffmpeg_and_ffprobe_are_actionable(monkeypatch):
    monkeypatch.setattr(readiness.shutil, "which", lambda name: None)
    assert "not on PATH" in readiness._ffmpeg_check(False).detail
    assert "not on PATH" in readiness._ffprobe_check(False).detail
