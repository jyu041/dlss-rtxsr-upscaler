from pathlib import Path


RUNNER = Path(__file__).parents[1] / "tools" / "run_dlssg_ab.ps1"


def test_resumable_runner_has_per_run_safety_controls():
    source = RUNNER.read_text(encoding="utf-8")
    assert "Read-PassJson" in source
    assert "START" in source and "HEARTBEAT" in source and "PASS" in source
    assert "PerRunTimeoutSeconds" in source
    assert "Start-Sleep -Milliseconds 500" in source
    assert "taskkill.exe /PID $process.Id /T /F" in source
    assert "RedirectStandardError $stderrPath" in source
    assert "existing PASS JSON" in source

