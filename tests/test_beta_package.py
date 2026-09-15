from pathlib import Path


def test_beta_builder_has_explicit_commit_hash_gate_and_external_boundaries():
    script = (Path(__file__).parents[1] / "tools" / "build_beta_package.ps1").read_text(encoding="utf-8")
    assert "Parameter(Mandatory=$true)][string]$SourceCommit" in script
    assert "Refusing non-production worker" in script
    assert "community_runtime_bundled = $false" in script
    assert "official_nvidia_runtime_bundled = $false" in script
    assert "driver_dlls_bundled = $false" in script
    assert "git -C $root ls-files src config" in script
