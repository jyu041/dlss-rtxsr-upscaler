import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
POLICY_EXE = ROOT / "native" / "dlssg_ampere_experiment" / "bin" / "bridge_policy_tests.exe"


def test_native_bridge_policy_cpu_cases():
    if not POLICY_EXE.exists():
        return
    completed = subprocess.run([str(POLICY_EXE)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
