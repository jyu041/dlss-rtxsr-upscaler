import json
from tools.check_portable_runtime import main as check_main

from src.core.portable_runtime import inspect


def test_portable_runtime_is_not_configured_without_manifest(tmp_path):
    assert inspect(tmp_path)["state"] == "NOT_CONFIGURED"


def test_portable_runtime_detects_identity_mismatch(tmp_path):
    (tmp_path / "build-manifest.json").write_text(json.dumps({"external_runtime_files": {"python": [{"path": "runtime/python/python.exe", "sha256": "A" * 64, "size_bytes": 4}]}}), encoding="utf-8")
    path = tmp_path / "runtime" / "python"; path.mkdir(parents=True); (path / "python.exe").write_bytes(b"bad!")
    assert inspect(tmp_path)["state"] == "BROKEN"


def test_portable_runtime_requires_all_launcher_tools(tmp_path):
    entries = []
    for relative, payload in (("runtime/python/python.exe", b"python"), ("runtime/tools/ffmpeg/ffmpeg.exe", b"ffmpeg"), ("runtime/tools/ffmpeg/ffprobe.exe", b"ffprobe")):
        path = tmp_path / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
        import hashlib
        entries.append({"path": relative, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)})
    (tmp_path / "build-manifest.json").write_text(json.dumps({"external_runtime_files": {"portable": entries}}), encoding="utf-8")
    assert inspect(tmp_path)["state"] == "READY"


def test_portable_launcher_check_fails_closed_without_manifest(tmp_path, capsys):
    assert check_main(["--root", str(tmp_path)]) == 1
    assert "NOT_CONFIGURED" in capsys.readouterr().out


def test_portable_runtime_detects_tampered_notice(tmp_path):
    notice = tmp_path / "licenses" / "runtime.txt"; notice.parent.mkdir(); notice.write_text("terms", encoding="utf-8")
    import hashlib
    entries = [{"path": "licenses/runtime.txt", "sha256": hashlib.sha256(b"terms").hexdigest(), "size_bytes": 5}]
    (tmp_path / "build-manifest.json").write_text(json.dumps({"external_runtime_files": {}, "external_runtime_notices": {"python": {"path": "licenses/runtime.txt", "sha256": entries[0]["sha256"], "size_bytes": 5}}}), encoding="utf-8")
    for relative, payload in (("runtime/python/python.exe", b"python"), ("runtime/tools/ffmpeg/ffmpeg.exe", b"ffmpeg"), ("runtime/tools/ffmpeg/ffprobe.exe", b"ffprobe")):
        path = tmp_path / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
    notice.write_text("changed", encoding="utf-8")
    assert inspect(tmp_path)["state"] == "BROKEN"
    assert "notice identity mismatch" in inspect(tmp_path)["detail"]
