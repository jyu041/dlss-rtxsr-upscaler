from pathlib import Path

from tools import cache_dlss5_v3_archive as cache


def test_valid_cached_archive_is_reused(tmp_path, monkeypatch):
    archive = tmp_path / "DLSS.5.Visual.Enhancer.v3.0.zip"
    archive.write_bytes(b"cached")
    calls = []

    monkeypatch.setattr(cache, "CACHE_ARCHIVE", archive)
    monkeypatch.setattr(cache, "verify_archive", lambda path: calls.append(("verify", path)))
    monkeypatch.setattr(
        cache,
        "require_download_network_context",
        lambda: calls.append(("network", None)),
    )
    monkeypatch.setattr(
        cache,
        "download_archive",
        lambda path: calls.append(("download", path)),
    )

    assert cache.ensure_cached_archive() == archive
    assert calls == [("verify", archive)]


def test_invalid_cached_archive_is_replaced(tmp_path, monkeypatch):
    archive = tmp_path / "DLSS.5.Visual.Enhancer.v3.0.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"bad")
    calls = []
    verification_count = 0

    monkeypatch.setattr(cache, "CACHE_ARCHIVE", archive)

    def verify(path: Path):
        nonlocal verification_count
        verification_count += 1
        calls.append(("verify", path))
        if verification_count == 1:
            raise ValueError("bad cache")

    def download(path: Path):
        calls.append(("download", path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"good")
        return path

    monkeypatch.setattr(cache, "verify_archive", verify)
    monkeypatch.setattr(
        cache,
        "require_download_network_context",
        lambda: calls.append(("network", None)),
    )
    monkeypatch.setattr(cache, "download_archive", download)

    assert cache.ensure_cached_archive() == archive
    assert calls == [
        ("verify", archive),
        ("network", None),
        ("download", archive),
        ("verify", archive),
    ]
    assert archive.read_bytes() == b"good"
