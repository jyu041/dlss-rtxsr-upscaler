"""Reusable containment helpers for experimental DLSS5 v10 application sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
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
            "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "
            f'"{str(path).replace(chr(34), chr(34) * 2)}"'
        )
        command = (
            "$p=Start-Process -FilePath 'powershell.exe' "
            f"-ArgumentList '{_quote_ps(argument)}' "
            "-WindowStyle Hidden -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
        )
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            verify,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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


def _is_expected_windows_console_host(process: psutil.Process) -> bool:
    """Allow only the real Windows console host used for hidden console plumbing.

    CREATE_NO_WINDOW normally avoids a console, but some Windows/runtime paths can
    still attach a system conhost.exe beneath the isolated Python host. That is OS
    infrastructure rather than an application-spawned helper. Keep the allowlist
    deliberately narrow: exact process name and exact %WINDIR%\\System32 path.
    """
    try:
        if process.name().casefold() != "conhost.exe":
            return False
        windir = os.environ.get("WINDIR")
        if not windir:
            return False
        expected = PureWindowsPath(windir) / "System32" / "conhost.exe"
        actual = PureWindowsPath(process.exe())
        return str(actual).casefold() == str(expected).casefold()
    except (psutil.Error, OSError, ValueError):
        return False


def _describe_process(process: psutil.Process) -> dict[str, object]:
    try:
        name = process.name()
    except (psutil.Error, OSError):
        name = "<unavailable>"
    return {"pid": process.pid, "name": name}


def assert_no_host_descendants(pid: int | None, stage: str) -> dict[str, object]:
    if pid is None:
        raise RuntimeError(f"v10 host PID unavailable at {stage}")
    try:
        root = psutil.Process(pid)
        observed = root.children(recursive=True)
    except (psutil.Error, OSError) as exc:
        raise RuntimeError(
            f"could not inspect v10 host process tree at {stage}: {exc}"
        ) from exc

    descendants: list[psutil.Process] = []
    allowed_console_hosts: list[dict[str, object]] = []
    for process in observed:
        try:
            if not process.is_running():
                continue
        except (psutil.NoSuchProcess, OSError):
            continue
        if _is_expected_windows_console_host(process):
            allowed_console_hosts.append(_describe_process(process))
        else:
            descendants.append(process)

    evidence = {
        "stage": stage,
        "host_pid": pid,
        "descendant_count": len(descendants),
        "descendants": [_describe_process(process) for process in descendants],
        "allowed_console_hosts": allowed_console_hosts,
    }
    if descendants:
        raise RuntimeError(
            f"unexpected child process spawned by v10 host at {stage}: "
            + ", ".join(
                f"{item['name']}({item['pid']})" for item in evidence["descendants"]
            )
        )
    return evidence
