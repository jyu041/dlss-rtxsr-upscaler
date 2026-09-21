from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v020_beta2_release_docs_match_source_install_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    notes = (ROOT / "docs" / "RELEASE_NOTES_v0.2.0-beta.2.md").read_text(encoding="utf-8")
    status = (ROOT / "docs" / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "v0.2.0-beta.2" in readme
    assert "v0.2.0-beta.2" in status
    assert "v0.2.0-beta.2" in changelog
    assert "git clone --branch v0.2.0-beta.2 --recurse-submodules" in notes
    assert "Enable DLSS 5 now? [Y/N]" in notes
    assert "DLSS 5 READY" in notes
    assert "no-Conda" in notes
    assert "one **DLSS 5** mode" in notes
