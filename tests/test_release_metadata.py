from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v020_beta3_release_docs_match_source_install_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    notes = (ROOT / "docs" / "RELEASE_NOTES_v0.2.0-beta.3.md").read_text(encoding="utf-8")
    status = (ROOT / "docs" / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "v0.2.0-beta.3" in readme
    assert "v0.2.0-beta.3" in status
    assert "v0.2.0-beta.3" in changelog
    assert "v0.2.0-beta.3 release notes" in docs_index
    assert "v0.2.0-beta.2 release notes](RELEASE_NOTES_v0.2.0-beta.2.md) | Current" not in docs_index
    assert "git clone --branch v0.2.0-beta.3 --recurse-submodules" in notes
    assert "Enable DLSS 5 now? [Y/N]" in notes
    assert "no-Conda" in notes
    assert "public-launch source beta" in notes
    assert "h264_nvenc" in notes
    assert "hevc_nvenc" in notes
    assert "Source code (zip/tar.gz)" in notes
    assert "Source code (zip/tar.gz)" in readme
