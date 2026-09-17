import zipfile
from pathlib import Path

import pytest

from tools import provision_dlss5_v3 as provision


EXPECTED_FILES = {
    "nvngx.dll",
    "renodx-dlss5.addon64",
    "nvngx_dlssnr.dll",
    "dxgi.dll",
    "nvngx_dlss.dll",
}


def _write_archive(path: Path, *, prefix: str = "DLSS5-v3") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{prefix}/README.txt", "ignored")
        archive.writestr(f"{prefix}/bin/runtime/ReShade.ini", "ignored runtime extra")
        for name in EXPECTED_FILES:
            archive.writestr(f"{prefix}/bin/runtime/{name}", name)
    return path


def test_v3_identity_is_pinned_to_public_upstream_release():
    assert provision.RELEASE_URL == (
        "https://github.com/Merserk/dlss5-visual-enhancer/releases/download/3.0/"
        "DLSS.5.Visual.Enhancer.v3.0.zip"
    )
    assert provision.ARCHIVE_SIZE_BYTES == 466_919_995
    assert provision.ARCHIVE_SHA256 == "6F0590D81677484F4ECDFAA5C44FC2A0E1A3835D33EEFC59D656E6C3BCF35F6A"
    assert set(provision.EXPECTED_RUNTIME_SHA256) == EXPECTED_FILES
    assert provision.EXPECTED_RUNTIME_SHA256["nvngx.dll"] == "AE871BF387B84E59154DD666BBB6C0E03F466FAA2BA99687D7144C13E69F3DDF"
    assert provision.EXPECTED_RUNTIME_SHA256["renodx-dlss5.addon64"] == "D5ADF82EB44B065F4C590AC91FE824BAB07AFEA0EB9F994BDE936710C8593952"
    assert provision.EXPECTED_RUNTIME_SHA256["nvngx_dlssnr.dll"] == "6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927"
    assert provision.EXPECTED_RUNTIME_SHA256["dxgi.dll"] == "0CEE63F9C9F13F3AC909C5B4903F4DBB4B719A7AB3B4F13B0DEAF83C814B94F7"
    assert provision.EXPECTED_RUNTIME_SHA256["nvngx_dlss.dll"] == "C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E"


def test_select_runtime_members_accepts_release_prefix_and_only_five_files(tmp_path):
    archive = _write_archive(tmp_path / "candidate.zip")
    selected = provision.select_runtime_members(archive)
    assert set(selected) == EXPECTED_FILES
    assert all("bin/runtime/" in item.filename.replace("\\", "/") for item in selected.values())


def test_select_runtime_members_rejects_duplicate_required_mapping(tmp_path):
    archive_path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in EXPECTED_FILES:
            archive.writestr(f"one/bin/runtime/{name}", name)
        archive.writestr("two/bin/runtime/nvngx.dll", "duplicate")
    with pytest.raises(ValueError, match="multiple archive members"):
        provision.select_runtime_members(archive_path)


def test_select_runtime_members_rejects_unsafe_namespace(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.txt", "bad")
        for name in EXPECTED_FILES:
            archive.writestr(f"bin/runtime/{name}", name)
    with pytest.raises(ValueError, match="unsafe archive member"):
        provision.select_runtime_members(archive_path)


def test_authenticode_records_must_cover_all_five_files():
    items = [
        {"file": name, "status": "NotSigned", "status_message": "unsigned"}
        for name in list(provision.EXPECTED_RUNTIME_SHA256)[:-1]
    ]
    with pytest.raises(RuntimeError, match="did not return all required runtime files"):
        provision._validate_authenticode_items(items)


def test_authenticode_falls_back_to_winverifytrust_when_powershell_is_unavailable(
    tmp_path, monkeypatch
):
    for name in provision.EXPECTED_RUNTIME_SHA256:
        (tmp_path / name).write_bytes(b"test")

    class Result:
        returncode = 1
        stdout = ""
        stderr = "Microsoft.PowerShell.Security could not be loaded"

    monkeypatch.setattr(provision.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(
        provision,
        "_winverifytrust_record",
        lambda path: {
            "file": path.name,
            "status": "NotSigned",
            "status_code": "0x800B0100",
            "status_message": "test fallback",
            "signer_subject": None,
            "signer_thumbprint": None,
        },
    )

    report = provision.authenticode_report(tmp_path)
    assert report["completed"] is True
    assert report["tool"] == "WinVerifyTrust"
    assert "PowerShell.Security" in report["powershell_fallback_reason"]
    assert [item["file"] for item in report["files"]] == list(
        provision.EXPECTED_RUNTIME_SHA256
    )


def test_approval_payload_preserves_security_contract():
    hashes = dict(provision.EXPECTED_RUNTIME_SHA256)
    auth = {
        "tool": "WinVerifyTrust",
        "completed": True,
        "files": [
            {"file": name, "status": "NotSigned", "status_code": "0x800B0100"}
            for name in provision.EXPECTED_RUNTIME_SHA256
        ],
    }
    scan = {"tool": "MpCmdRun.exe", "status": "passed", "exit_code": 0}
    firewall = {"rule_name": provision.FIREWALL_RULE_NAME, "verified": True}
    payload = provision.approval_payload(provision.RUNTIME_DIR, hashes, auth, scan, firewall)

    assert payload["approved"] is True
    assert payload["approved_by_user"] is True
    assert payload["runtime_dir"] == "runtime/dlss5-v3"
    assert payload["archive_sha256"] == provision.ARCHIVE_SHA256
    assert payload["authenticode"] == auth
    assert payload["malware_scan"] == scan
    assert payload["firewall"] == firewall
    for filename, key in provision.APPROVAL_HASH_KEYS.items():
        assert payload[key] == hashes[filename]
