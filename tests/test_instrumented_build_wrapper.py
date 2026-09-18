from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_instrumented_build_wrapper_captures_native_stderr_without_powershell_error_records():
    script = (ROOT / "tools" / "build_validate_dlssg_instrumented.ps1").read_text(encoding="utf-8")
    assert "Start-Process -FilePath $worker -ArgumentList '--selftest'" in script
    assert "-RedirectStandardOutput $selftestStdout" in script
    assert "-RedirectStandardError $selftestStderr" in script
    assert "$selftestCode = $selftestProcess.ExitCode" in script
    assert "& $worker --selftest 2>&1" not in script
    assert "SELFTEST_COMPLETE" in script
