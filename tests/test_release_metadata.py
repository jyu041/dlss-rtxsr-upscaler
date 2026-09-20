from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v020_beta1_release_docs_match_source_install_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    notes = (ROOT / "docs" / "RELEASE_NOTES_v0.2.0-beta.1.md").read_text(encoding="utf-8")
    status = (ROOT / "docs" / "PROJECT_STATUS.md").read_text(encoding="utf-8")

    assert "v0.2.0-beta.1" in readme
    assert "v0.2.0-beta.1" in status
    assert "validated source-install" in notes
    assert "git clone --branch v0.2.0-beta.1 --recurse-submodules" in notes
    assert "no-Conda portable application" in notes
    assert "DLSS 5 v10 Experimental" in notes
