from pathlib import Path


def test_beta_builder_has_explicit_commit_hash_gate_and_external_boundaries():
    script = (Path(__file__).parents[1] / "tools" / "build_beta_package.ps1").read_text(encoding="utf-8")
    assert "Parameter(Mandatory=$true)][string]$SourceCommit" in script
    assert "hash mismatch" in script
    assert "$DlssSrHostPath" in script
    assert "$DlssSrRuntimePath" in script
    assert "$NvidiaSdkLicensePath" in script
    assert "Git LFS pointer" in script
    assert "NVIDIA_RTX_SDK_LICENSE.txt" in script
    assert "private_resource_commit" in script
    assert "machine_attestation_bundled=$false" in script
    assert "git -C $root ls-files src config" in script


def test_beta_builder_has_exact_identity_gates_and_clean_package_policy():
    script = (Path(__file__).parents[1] / "tools" / "build_beta_package.ps1").read_text(encoding="utf-8")
    for identity in ("C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916", "E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB", "3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983", "3027F23CA5A46DD9CB8183FBD522983A86F64D7DAAC5982912BF9F214671F294"):
        assert identity in script
    assert "selftest" in script and "attestation.json" not in script
