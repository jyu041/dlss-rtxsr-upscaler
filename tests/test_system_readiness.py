from types import SimpleNamespace

from src.core import system_readiness


def test_gpu_query_is_bounded_and_parses_generation(monkeypatch):
    monkeypatch.setattr(system_readiness, "tool", lambda name: "nvidia-smi.exe")
    monkeypatch.setattr(system_readiness.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="NVIDIA GeForce RTX 3070 Ti, 610.62, 8192, 8.6\n", stderr=""))
    result = system_readiness._gpu_query()
    assert result["state"] == "READY"
    assert result["generation"] == 30


def test_nvenc_requires_both_baseline_encoders(monkeypatch):
    monkeypatch.setattr(system_readiness, "tool", lambda name: "ffmpeg.exe")
    monkeypatch.setattr(system_readiness.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="h264_nvenc\nhevc_nvenc\n", stderr=""))
    assert system_readiness._nvenc()["state"] == "READY"


def test_missing_tools_are_explicit(monkeypatch):
    monkeypatch.setattr(system_readiness, "tool", lambda name: None)
    assert system_readiness._gpu_query()["state"] == "MISSING"
    assert system_readiness._nvenc()["state"] == "MISSING"
