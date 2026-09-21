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

### DLSS 5

The UI exposes one DLSS 5 mode. Check **Configuration → DLSS 5 preferred
runtime readiness** first. **Refresh DLSS 5 runtime preflight** verifies and
stages the pinned v10 runtime, refreshes Defender evidence, and prepares the
isolated application path. When that preferred runtime is ready it is selected
automatically.

If the preferred runtime is not ready, the application may use the validated
v3 compatibility backend internally if it has been provisioned. For that
fallback, check the local approval manifest, exact runtime hashes, Defender
evidence, Feature-18 self-test, and exact outbound firewall block:

```powershell
python -m src.backends.dlss5_diagnostics
```

Use `--self-test` only when an approved compatibility runtime and compatible RTX
hardware are already present.

For measurements use `python -m src.backends.dlss5_benchmark`; it writes an
ignored JSON report and continues after a timed-out resolution. An encoder error
after successful Feature-18 output is an FFmpeg/NVENC failure rather than
evidence that Feature 18 itself failed.

Reduced NR working resolution changes the internal Neural Rendering workload,
not final video dimensions. The preferred v10 path now supports the same
Auto/100/87.5/75/67/50% application-level working-resolution and residual
recomposition controls. The current preferred-runtime hardware boundary remains
SDR RGBA8, 1.0x output, and up to 1920x1080-equivalent native input.

If CUDA recomposition cannot initialize on the selected GPU, `auto` records the
reason and uses the CPU reference compositor. The explicit `cuda` option fails
rather than silently falling back.

The v3 compatibility runtime does not implement the v10-only neural-pass,
face/skin, grain, native-shimmer, or NVOF-preference controls. If the preferred
runtime is unavailable and one of those controls is changed from its compatible
default, the job fails explicitly instead of silently ignoring the setting.

## General behavior

Ordinary application startup does not download replacement runtimes and the
application never silently switches enhancement families. The single DLSS 5
mode may use its retained compatibility runtime, but the status and completion
message explicitly report that fallback.

DLSS paths are SDR-oriented and do not promise HDR preservation. Performance
and output characteristics are hardware/runtime/content dependent.

When sharing diagnostic or benchmark output, inspect it first and redact local
filesystem paths or other machine-specific information.
