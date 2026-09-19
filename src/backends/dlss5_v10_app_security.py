"""Reusable containment helpers for experimental DLSS5 v10 application sessions."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

import psutil


def _quote_ps(value: str) -> str:
    return value.replace("'", "''")


def _run_elevated_script(script: str, *, timeout: int = 120) -> None:
    with tempfile.TemporaryDirectory(prefix="nve-dlss5-v10-firewall-") as temporary:
        path = Path(temporary) / "firewall.ps1"
        path.write_text(script, encoding="utf-8")
        argument = (
            "-NoProfile -ExecutionPolicy Bypass -File "
            f'"{str(path).replace(chr(34), chr(34) * 2)}"'
        )
        command = (
            "$p=Start-Process -FilePath 'powershell.exe' "
            f"-ArgumentList '{_quote_ps(argument)}' "
            "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                result.stderr.strip()
                or result.stdout.strip()
                or f"elevated firewall command exited {result.returncode}"
            )


def install_temporary_firewall_block(program: Path, rule_name: str) -> None:
    program = Path(program).resolve()
    script = (
        "$ErrorActionPreference='Stop'\n"
        f"$name='{_quote_ps(rule_name)}'\n"
        f"$program='{_quote_ps(str(program))}'\n"
        "Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | "
        "Remove-NetFirewallRule -ErrorAction SilentlyContinue\n"
        "New-NetFirewallRule -DisplayName $name -Direction Outbound -Action Block "
        "-Program $program -Profile Any -Enabled True | Out-Null\n"
    )
    _run_elevated_script(script)

    verify = (
        f"$r=Get-NetFirewallRule -DisplayName '{_quote_ps(rule_name)}' "
        "-ErrorAction Stop; "
        "$a=@($r | Get-NetFirewallApplicationFilter); "
        "[pscustomobject]@{direction=$r.Direction.ToString();"
        "action=$r.Action.ToString();enabled=$r.Enabled.ToString();"
        "program=($a.Program -join ';')} | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", verify],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("temporary v10 firewall rule could not be verified")
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError("temporary v10 firewall verification returned invalid JSON") from exc
    if (
        data.get("direction") != "Outbound"
        or data.get("action") != "Block"
        or data.get("enabled") != "True"
        or str(data.get("program", "")).casefold() != str(program).casefold()
    ):
        raise RuntimeError(f"temporary v10 firewall verification mismatch: {data}")


def remove_temporary_firewall_block(rule_name: str) -> None:
    script = (
        "$ErrorActionPreference='Stop'\n"
        f"Get-NetFirewallRule -DisplayName '{_quote_ps(rule_name)}' "
        "-ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction Stop\n"
    )
    _run_elevated_script(script)


def assert_no_host_descendants(pid: int | None, stage: str) -> dict[str, object]:
    if pid is None:
        raise RuntimeError(f"v10 host PID unavailable at {stage}")
    try:
        root = psutil.Process(pid)
        descendants = [
            process for process in root.children(recursive=True) if process.is_running()
        ]
    except (psutil.Error, OSError) as exc:
        raise RuntimeError(
            f"could not inspect v10 host process tree at {stage}: {exc}"
        ) from exc
    evidence = {
        "stage": stage,
        "host_pid": pid,
        "descendant_count": len(descendants),
        "descendants": [
            {"pid": process.pid, "name": process.name()} for process in descendants
        ],
    }
    if descendants:
        raise RuntimeError(
            f"unexpected child process spawned by v10 host at {stage}: "
            + ", ".join(
                f"{item['name']}({item['pid']})" for item in evidence["descendants"]
            )
        )
    return evidence
