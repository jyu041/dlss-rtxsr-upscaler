from pathlib import Path

from tools import provision_dlss5_v10 as provision


class _Spec:
    pass


def test_cached_v10_archive_is_reused_without_download(tmp_path, monkeypatch):
    cache = tmp_path / "Visual.Enhancer.v10.0.zip"
    cache.write_bytes(b"cached")
    calls = {"downloads": 0, "verified": 0}

    class Manager:
        specs = {provision.RUNTIME_ID: _Spec()}

        def download(self, runtime_id, target, progress=None):
            calls["downloads"] += 1
            raise AssertionError("verified cache should not be downloaded again")

    monkeypatch.setattr(provision, "DEFAULT_ARCHIVE", cache)
    monkeypatch.setattr(provision, "RuntimeManager", lambda *_args, **_kwargs: Manager())

    def verify(path, spec):
        assert Path(path) == cache.resolve()
        calls["verified"] += 1

    monkeypatch.setattr(provision, "verify_artifact", verify)

    assert provision.ensure_cached_archive() == cache.resolve()
    assert calls == {"downloads": 0, "verified": 1}


def test_supplied_v10_archive_is_copied_into_managed_cache(tmp_path, monkeypatch):
    source = tmp_path / "source.zip"
    source.write_bytes(b"exact")
    cache = tmp_path / "managed" / "Visual.Enhancer.v10.0.zip"

    class Manager:
        specs = {provision.RUNTIME_ID: _Spec()}

    monkeypatch.setattr(provision, "DEFAULT_ARCHIVE", cache)
    monkeypatch.setattr(provision, "RuntimeManager", lambda *_args, **_kwargs: Manager())
    monkeypatch.setattr(provision, "verify_artifact", lambda path, spec: None)

    result = provision.ensure_cached_archive(source)
    assert result == cache.resolve()
    assert cache.read_bytes() == b"exact"


def test_prepare_v10_uses_same_cached_archive_for_stage_and_status(tmp_path, monkeypatch):
    archive = tmp_path / "Visual.Enhancer.v10.0.zip"
    archive.write_bytes(b"exact")
    captured = {}

    monkeypatch.setattr(
        provision,
        "ensure_cached_archive",
        lambda supplied=None, allow_download=True: archive,
    )

    def stage(path, destination, report_path):
        captured["archive"] = path
        captured["destination"] = destination
        captured["report"] = report_path
        return {"ok": True}

    class Status:
        available = True
        state = "EXPERIMENTAL READY"
        reason = "clean preflight"

    class Backend:
        def status(self):
            return Status()

    monkeypatch.setattr(provision, "stage_candidate", stage)
    monkeypatch.setattr(provision, "DLSS5V10ExperimentalBackend", Backend)

    result = provision.prepare_dlss5_v10()
    assert captured["archive"] == archive
    assert result["state"] == "EXPERIMENTAL READY"
    assert result["report"] == {"ok": True}


def test_cached_preflight_refresh_is_fail_closed(monkeypatch):
    monkeypatch.setattr(
        provision,
        "prepare_dlss5_v10",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("scan failed")),
    )
    assert provision.refresh_preflight_from_cache() is False
