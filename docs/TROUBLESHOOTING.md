# Troubleshooting

Start with the **Diagnostics** page in the UI or run
`python -m src.core.diagnostics` inside the dedicated Conda environment.

If FFmpeg is unavailable, install a compatible FFmpeg/FFprobe build and ensure
both commands are on `PATH`. Source setup requires both `h264_nvenc` and
`hevc_nvenc` to be exposed by FFmpeg.

## Backend readiness

### RTX VSR

Verify the official `nvidia-vfx` package, NVIDIA driver, and compatible RTX
hardware. Use `python tools/check_rtx_vsr_readiness.py` for the explicit
readiness probe.

### DLSS SR

Open **Configuration → DLSS SR readiness** and run validation. A verified
host/runtime can remain installed even when the local GPU/driver self-test does
not pass; the UI reports the readiness reason rather than falling back to
another processor.

### DLSS Frame Generation

Verify the managed C55 worker, SM86 direct-host runtime, and official provider
through Runtime Manager. The normal profile is C55/grid1. Grid4 is an explicit
experimental profile with its own pinned worker identity.

### DLSS 5 v3

Check the local approval manifest, exact runtime hashes, Defender evidence,
Feature-18 self-test, and the exact outbound Firewall block. For a passive
report run:

```powershell
python -m src.backends.dlss5_diagnostics
```

Use `--self-test` only when an approved runtime and compatible RTX hardware
are already present.

For measurements use `python -m src.backends.dlss5_benchmark`; it writes an
ignored JSON report and continues after a timed-out resolution. An encoder
error after successful Feature-18 output is an FFmpeg/NVENC failure rather than
evidence that Feature 18 itself failed.

If reduced NR is selected with a DLSS5 output scale other than 1.0x, the job is
rejected intentionally. Select `100% (Native)` NR working resolution or use
1.0x DLSS5 output. Reduced working resolution changes the internal
motion/Feature-18 workload, not final video dimensions.

If CUDA recomposition cannot select the same unambiguous GPU as the DLSS5
runtime, `auto` records the reason and uses the CPU reference compositor. The
explicit `cuda` option fails rather than silently falling back.

### DLSS 5 v10 Experimental

v10 is not provisioned by normal setup. Open **Configuration → DLSS 5 v10
experimental readiness** and run **Refresh DLSS 5 v10 preflight**. This verifies
the pinned archive/runtime identity, stages the candidate, and reruns the
required static/Defender preflight.

The current application path is intentionally restricted to SDR RGBA8, 1.0x,
and up to 1920x1080-equivalent input. Failure of preflight, containment,
process-tree checks, NGX/CUDA results, or clean shutdown is treated as a hard
v10 render failure.

## General behavior

Ordinary application startup does not download replacement runtimes and the
application never silently switches enhancement backends.

DLSS paths are SDR-oriented and do not promise HDR preservation. Performance
and output characteristics are hardware/runtime/content dependent.

When sharing diagnostic or benchmark output, inspect it first and redact local
filesystem paths or other machine-specific information.
