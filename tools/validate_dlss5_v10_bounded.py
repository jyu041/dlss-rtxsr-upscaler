"""Run the first bounded DLSS5 v10 native compatibility experiment.

This is intentionally separate from normal setup/start. It requires the exact
Defender-gated preflight report, an explicit acknowledgement token, a temporary
outbound firewall block for the exact Python interpreter, and is limited to one
256x256 / 1.0x reset frame.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlss5_metrics import effect_metrics, effect_observed  # noqa: E402
from src.backends.dlss5_v10_client import EXPERIMENT_ACK, V10ProtocolClient  # noqa: E402
from src.backends.dlss5_v10_protocol import CreateRequest, FrameRequest  # noqa: E402
from src.backends.dlss5_v10_security import validate_preflight_report  # noqa: E402
DEFAULT_RUNTIME = (
    ROOT / "runtime" / "dlss5" / "neuroframe-v10-candidate"
    / "bin" / "runtime" / "dlssnr"
)
DEFAULT_PREFLIGHT = ROOT / "runtime" / "audit" / "dlss5-v10-preflight.json"
DEFAULT_OUTPUT = ROOT / "runtime" / "audit" / "dlss5-v10-bounded-hardware.json"
NGX_RESULT_SUCCESS = 1
BOUNDED_RGBA_BYTES = 256 * 256 * 4


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
    program = program.resolve()
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
            process
            for process in root.children(recursive=True)
            if process.is_running()
        ]
    except (psutil.Error, OSError) as exc:
        raise RuntimeError(f"could not inspect v10 host process tree at {stage}: {exc}") from exc
    evidence = {
        "stage": stage,
        "host_pid": pid,
        "descendant_count": len(descendants),
        "descendants": [
            {
                "pid": process.pid,
                "name": process.name(),
            }
            for process in descendants
        ],
    }
    if descendants:
        raise RuntimeError(
            f"unexpected child process spawned by v10 host at {stage}: "
            + ", ".join(f"{item['name']}({item['pid']})" for item in evidence["descendants"])
        )
    return evidence


def validate_bounded_hello(hello: dict[str, object]) -> None:
    contract = hello.get("bounded_contract")
    expected = {
        "input": [256, 256],
        "processing_scale": 1.0,
        "max_frames": 1,
    }
    if contract != expected:
        raise RuntimeError(
            f"bounded v10 host contract mismatch: expected {expected}, got {contract!r}"
        )


def validate_feature_result(output) -> None:
    if (output.width, output.height) != (256, 256):
        raise RuntimeError(
            f"bounded v10 output geometry must remain 256x256, got "
            f"{output.width}x{output.height}"
        )
    if output.ngx_create_result != NGX_RESULT_SUCCESS:
        raise RuntimeError(
            f"Feature-18 NGX create did not return success: "
            f"0x{output.ngx_create_result & 0xFFFFFFFF:08X}"
        )
    if output.ngx_evaluate_result != NGX_RESULT_SUCCESS:
        raise RuntimeError(
            f"Feature-18 NGX evaluate did not return success: "
            f"0x{output.ngx_evaluate_result & 0xFFFFFFFF:08X}"
        )
    if len(output.rgba) != BOUNDED_RGBA_BYTES:
        raise RuntimeError(
            f"bounded v10 output byte count {len(output.rgba)} != {BOUNDED_RGBA_BYTES}"
        )


def synthetic_frame() -> np.ndarray:
    width = height = 256
    y, x = np.mgrid[0:height, 0:width]
    frame = np.empty((height, width, 4), dtype=np.uint8)
    frame[..., 0] = (x * 3 + y) % 256
    frame[..., 1] = (x + y * 2) % 256
    frame[..., 2] = ((x ^ y) * 5) % 256
    frame[..., 3] = 255
    frame[80:176, 96:160, :3] = np.array([230, 180, 60], dtype=np.uint8)
    return frame


def run_bounded(
    runtime: Path,
    preflight: Path,
    *,
    gpu_ordinal: int,
) -> dict[str, object]:
    preflight_evidence = validate_preflight_report(runtime, preflight)
    python = Path(sys.executable).resolve()
    rule_name = f"NVE DLSS5 v10 bounded test {__import__('os').getpid()}"
    firewall_installed = False
    client = V10ProtocolClient(
        python=python,
        start_timeout=15.0,
        frame_timeout=45.0,
        close_grace=1.0,
    )
    started = time.perf_counter()

    report: dict[str, object] = {
        "schema": 1,
        "status": "STARTED",
        "native_executed": False,
        "normal_backend_changed": False,
        "runtime": str(runtime.resolve()),
        "preflight": str(preflight.resolve()),
        "preflight_age_seconds": preflight_evidence.get("preflight_age_seconds"),
        "defender": preflight_evidence.get("malware_scan"),
        "python": str(python),
        "gpu_ordinal": gpu_ordinal,
        "dimensions": [256, 256],
        "processing_scale": 1.0,
        "frame_count": 1,
        "firewall_rule": rule_name,
        "process_tree_checks": [],
    }

    try:
        install_temporary_firewall_block(python, rule_name)
        firewall_installed = True
        report["firewall_installed"] = True

        hello = client.start_native_experimental(
            runtime,
            preflight,
            acknowledgement=EXPERIMENT_ACK,
        )
        report["hello"] = hello
        validate_bounded_hello(hello)
        report["process_tree_checks"].append(
            assert_no_host_descendants(client.pid, "after_hello")
        )

        create = client.create(
            CreateRequest(
                256,
                256,
                gpu_ordinal=gpu_ordinal,
                processing_scale=1.0,
                style=0,
                intensity=1.0,
                nr_passes=1,
                local_tone=1.0,
                local_structure=1.0,
                skin_structure=-1.0,
                color_strength=1.0,
                tone_preservation=0.0,
                face_skin_protection=0.0,
                grain_preservation=0.0,
                shimmer_suppression=0.70,
                automatic_mask=False,
                prefer_nvof=False,
            )
        )
        report["create"] = create
        report["native_executed"] = bool(create.get("native_loaded") is True)
        if create.get("output_size") != [256, 256]:
            raise RuntimeError(
                f"bounded v10 CREATE output_size mismatch: {create.get('output_size')!r}"
            )
        report["process_tree_checks"].append(
            assert_no_host_descendants(client.pid, "after_create")
        )

        initialization = create.get("initialization", {})
        gpu_name = str(initialization.get("gpu_name", ""))
        bridge_abi_version = initialization.get("bridge_abi_version")
        initialized_gpu_ordinal = initialization.get("gpu_ordinal")
        if bridge_abi_version != 6:
            raise RuntimeError(
                f"bounded v10 milestone requires bridge ABI 6, got {bridge_abi_version!r}"
            )
        if initialized_gpu_ordinal != gpu_ordinal:
            raise RuntimeError(
                f"bounded v10 GPU ordinal mismatch requested={gpu_ordinal} "
                f"initialized={initialized_gpu_ordinal!r}"
            )
        if "RTX 3070" not in gpu_name:
            raise RuntimeError(
                f"bounded v10 milestone requires the RTX 3070/3070 Ti path, got {gpu_name!r}"
            )

        source = synthetic_frame()
        frame_started = time.perf_counter()
        output = client.process_frame(
            FrameRequest(timestamp=0, reset=True, rgba=source.tobytes())
        )
        report["frame_roundtrip_seconds"] = time.perf_counter() - frame_started
        report["process_tree_checks"].append(
            assert_no_host_descendants(client.pid, "after_frame")
        )
        validate_feature_result(output)
        report["feature_evidence"] = {
            "ngx_create_result": output.ngx_create_result,
            "ngx_evaluate_result": output.ngx_evaluate_result,
            "cuda_result": output.cuda_result,
            "scene_reset": output.scene_reset,
            "scene_score": output.scene_score,
            "upload_bytes": output.upload_bytes,
            "download_bytes": output.download_bytes,
        }

        rendered = np.frombuffer(output.rgba, dtype=np.uint8).reshape(256, 256, 4)
        metrics = effect_metrics(source, rendered)
        observed = effect_observed(metrics)
        report["effect_metrics"] = metrics
        report["nr_effect_observed"] = observed
        if not observed:
            raise RuntimeError(
                "bounded v10 call returned but did not produce a measurable Neural Rendering effect"
            )

        report["close"] = client.close()
        if report["close"] != "CLOSED":
            raise RuntimeError(f"bounded v10 host did not close cleanly: {report['close']}")
        report["status"] = "PASS"
        return report
    except BaseException as exc:
        report["status"] = "FAIL"
        report["error"] = str(exc)
        try:
            report["abort"] = client.abort()
        except Exception as abort_exc:
            report["abort_error"] = str(abort_exc)
        return report
    finally:
        report["total_seconds"] = time.perf_counter() - started
        if firewall_installed:
            try:
                remove_temporary_firewall_block(rule_name)
                report["firewall_removed"] = True
            except Exception as exc:
                report["firewall_removed"] = False
                report["firewall_remove_error"] = str(exc)
                report["status"] = "FAIL"
                report.setdefault(
                    "error",
                    "bounded v10 firewall cleanup failed; remove the temporary rule manually",
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gpu-ordinal", type=int, default=0)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute or args.ack != EXPERIMENT_ACK:
        print(
            "BLOCKED: bounded v10 native execution requires --execute "
            f"--ack {EXPERIMENT_ACK}",
            file=sys.stderr,
        )
        return 2
    report = run_bounded(
        args.runtime.expanduser().resolve(),
        args.preflight.expanduser().resolve(),
        gpu_ordinal=args.gpu_ordinal,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
