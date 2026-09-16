import json

from tools.manage_runtime import main


def _manifest(path):
    path.write_text(json.dumps({"runtimes": [{
        "id": "demo", "name": "Demo", "backend": "demo", "version": "1",
        "source": "https://example.invalid/source", "source_url": "https://example.invalid/source",
        "artifact_url": "https://example.invalid/demo.zip", "sha256": None, "size_bytes": None,
        "archive_type": "zip", "allowlist": ["payload.bin"], "destination": "demo",
        "policy": "UPSTREAM_DOWNLOAD",
    }]}), encoding="utf-8")


def test_inventory_command_is_read_only(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    assert main(["--manifest", str(manifest), "--root", str(tmp_path / "runtime"), "inventory"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["state"] == "NOT_INSTALLED"


def test_verify_command_reports_missing_runtime_without_download(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    assert main(["--manifest", str(manifest), "--root", str(tmp_path / "runtime"), "verify", "demo"]) == 1
    assert json.loads(capsys.readouterr().out)["detail"] == "runtime is NOT_INSTALLED"


def test_unknown_runtime_is_a_concise_cli_error(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    assert main(["--manifest", str(manifest), "--root", str(tmp_path / "runtime"), "verify", "missing"]) == 1
    assert "runtime command failed:" in capsys.readouterr().err
