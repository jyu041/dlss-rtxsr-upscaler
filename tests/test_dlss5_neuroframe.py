from src.backends import dlss5_neuroframe as candidate


def test_missing_neuroframe_candidate_is_not_installed(tmp_path):
    result = candidate.inspect_candidate(tmp_path / "missing")
    assert result.state == "NOT_INSTALLED" and not result.available


def test_neuroframe_candidate_requires_all_pinned_files(tmp_path):
    runtime = tmp_path / "candidate"
    runtime.mkdir()
    name, (size, _digest) = next(iter(candidate.EXPECTED_FILES.items()))
    (runtime / name).write_bytes(b"wrong")
    result = candidate.inspect_candidate(runtime)
    assert result.state == "IDENTITY_MISMATCH"


def test_matching_candidate_is_static_only(monkeypatch, tmp_path):
    runtime = tmp_path / "candidate"
    runtime.mkdir()
    expected = {"a.dll": (3, "A" * 64), "b.dll": (3, "B" * 64), "c.dll": (3, "C" * 64)}
    monkeypatch.setattr(candidate, "EXPECTED_FILES", expected)
    for name, (_size, _digest) in expected.items():
        (runtime / name).write_bytes(b"abc")
    monkeypatch.setattr(candidate, "_sha256", lambda path: expected[path.name][1])
    result = candidate.inspect_candidate(runtime)
    assert result.state == "STATIC_ONLY" and not result.available
