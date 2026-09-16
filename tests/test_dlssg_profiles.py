import json
from pathlib import Path

from src.core.dlssg_profiles import (
    CANDIDATE_INI_SHA256,
    CANDIDATE_RUNTIME_SHA256,
    CANDIDATE_RUNTIME_SIZE,
    LEGACY_RUNTIME_SHA256,
    LEGACY_RUNTIME_SIZE,
    profile,
)
from src.runtime_manager.core import RuntimeManager, RuntimeSpec


def test_manifest_binds_candidate_to_exact_upstream_commit_and_identity():
    manager = RuntimeManager(Path("src/runtime_manager/manifest.json"), Path("runtime"))
    candidate = manager.specs["dlssg-sm86-0.3.1-candidate"]
    files = {item.path: item for item in candidate.files}
    assert candidate.source != candidate.source_url
    assert candidate.source_url.endswith("117faf5c70333b34160f5d21d01c222261cc5af1")
    assert files["version.dll"].sha256 == CANDIDATE_RUNTIME_SHA256
    assert files["version.dll"].size_bytes == CANDIDATE_RUNTIME_SIZE
    assert files["dlssg_sm86.ini"].sha256 == CANDIDATE_INI_SHA256
    assert files["version.dll"].sha256 != LEGACY_RUNTIME_SHA256
    assert files["version.dll"].size_bytes != LEGACY_RUNTIME_SIZE


def test_profiles_keep_legacy_and_candidate_distinct():
    legacy, candidate = profile("legacy"), profile("candidate-0.3.1")
    assert legacy.runtime_sha256 != candidate.runtime_sha256
    assert legacy.runtime_size != candidate.runtime_size
    assert legacy.source_commit != candidate.source_commit
    assert legacy.compatibility_required is False
    assert candidate.compatibility_required is True


def test_runtime_spec_preserves_independent_source_field():
    spec = RuntimeSpec.from_dict({
        "id": "x", "name": "x", "backend": "x", "version": "1",
        "source": "https://example.invalid/project",
        "source_url": "https://example.invalid/commit/abc",
        "archive_type": "files", "allowlist": ["x.txt"], "destination": "x",
        "policy": "USER_SUPPLIED",
    })
    assert spec.source == "https://example.invalid/project"
    assert spec.source_url.endswith("/abc")
