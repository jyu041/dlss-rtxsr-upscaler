from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v020_beta1_release_metadata_matches_source_install_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    notes = (ROOT / "docs" / "RELEASE_NOTES_v0.2.0-beta.1.md").read_text(encoding="utf-8")
    status = (ROOT / "docs" / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "publish-v0.2.0-beta.1.yml").read_text(
        encoding="utf-8"
    )

    assert "v0.2.0-beta.1" in readme
    assert "v0.2.0-beta.1" in status
    assert "validated source-install workflow" in notes
    assert "git clone --branch v0.2.0-beta.1 --recurse-submodules" in notes
    assert "does **not** include a no-Conda portable application bundle" in notes
    assert "DLSS 5 v10 Experimental" in notes

    assert 'TAG: "v0.2.0-beta.1"' in workflow
    assert "ordinary-tests.yml" in workflow
    assert "--prerelease" in workflow
    assert "--target \"$GITHUB_SHA\"" in workflow
    assert "docs/RELEASE_NOTES_v0.2.0-beta.1.md" in workflow
