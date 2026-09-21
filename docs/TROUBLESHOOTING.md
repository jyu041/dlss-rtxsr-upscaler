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

Normal installation is handled by `setup.bat`. If you answered Yes to
**Enable DLSS 5 now?**, setup should leave the preferred v10 runtime staged and
ready without any additional UI action.

If DLSS 5 is unavailable later, use **Configuration → DLSS 5 runtime → Install /
Repair DLSS 5**. That action uses the same managed provisioner as setup: it
reuses the verified cached v10 archive when possible, otherwise downloads the
exact pinned archive, then verifies/stages it and refreshes the Microsoft
Defender preflight.

The verified archive is cached at:

```text
runtime/downloads/Visual.Enhancer.v10.0.zip
```

A time-expired Defender preflight is normally refreshed automatically from that
cache when the unified DLSS 5 backend is checked. This local refresh does not
require another download.

If provisioning fails, run the same entry point from PowerShell to get the
direct error:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\provision_dlss5_v10.py
```

Reduced NR working resolution changes the internal Neural Rendering workload,
not final video dimensions. The preferred v10 path supports
Auto/100/87.5/75/67/50% application-level working resolution plus residual
recomposition. The current preferred-runtime hardware boundary remains SDR
RGBA8, 1.0x output, and up to 1920x1080-equivalent native input.

If CUDA recomposition cannot initialize on the selected GPU, `auto` records the
reason and uses the CPU reference compositor. The explicit `cuda` option fails
rather than silently falling back.

The older v3 compatibility implementation is not part of normal onboarding. An
existing/manual legacy v3 installation may still be used internally if v10 is
unavailable, and the UI explicitly reports that compatibility fallback.

## General behavior

Ordinary application startup does not download replacement runtimes and the
application never silently switches enhancement families. The single DLSS 5
mode may use its retained compatibility runtime, but the status and completion
message explicitly report that fallback.

DLSS paths are SDR-oriented and do not promise HDR preservation. Performance
and output characteristics are hardware/runtime/content dependent.

When sharing diagnostic or benchmark output, inspect it first and redact local
filesystem paths or other machine-specific information.
