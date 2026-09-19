# Testing

Run deterministic tests explicitly against the repository test directory:

```powershell
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pytest
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pip check
```

The ordinary suite covers paths, configuration, media helpers, progress,
monitoring, UI behavior, cancellation, presets, and backend non-fallback
behavior. Hardware tests are explicit and may be skipped when the relevant
local runtime is absent. A skipped hardware test is not a successful backend
validation.

Backend validation classes:

- RTX VSR: run `python tools/check_rtx_vsr_readiness.py` for static API
  inspection plus one process-isolated GPU smoke test. The child emits
  heartbeat lines and is terminated after the hard timeout if native NVIDIA
  code stops responding.
- DLSS SR: native D3D12 host, approved NGX hash, and Quality self-test.
- DLSS5: user-approved runtime, firewall check, protocol test, and signed
  Feature-18 evidence.

DLSS5 diagnostics and the benchmark are explicit commands and are not part of
pytest:

```powershell
python -m src.backends.dlss5_diagnostics
python -m src.backends.dlss5_benchmark --frames 24 --warmup 4
python -m src.backends.dlss5_benchmark --resolutions 1920x1080 --working-scales 1,0.75,0.6666666667,0.5 --frames 24 --warmup 4
python -m src.backends.dlss5_benchmark --resolutions 1920x1080 --working-scales 0.75,0.6666666667,0.5 --recompose-backends cpu --frames 24 --warmup 4
```

The benchmark uses synthetic frames at 128x128 (contract reference),
960x540, 1280x720, 1920x1080, and 2560x1440. Each case is isolated and has a
bounded timeout. Use `DLSS5_HARDWARE_TEST=1` only for the existing integration
regression tests, not for performance measurement.

Feature submit FPS is only the CPU-side `session.submit()` rate. Motion-plus-
submit and processing-loop FPS include the serial work used by the production
backend. Reduced NR runs motion and Feature 18 at the working resolution, then
recomposes the residual onto the native frame; it currently requires output
scale 1.0x.

Use `--recompose-backends cuda` for the PyTorch CUDA compositor or `auto` for
CUDA preference with initialization-time CPU fallback. CUDA-specific tests skip
when CUDA is unavailable. CUDA timings are device-event timings; wall-clock
recomposition remains the authoritative latency measurement.

Use synthetic or owned media. Do not run unrestricted recursive pytest
discovery when an extracted local runtime tree exists; target `tests`
explicitly.

## DLSS5 v10 bounded research gates

The normal v10 application backend remains disabled. The isolated research
sequence is intentionally progressive:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_bounded.ps1 -Execute
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_temporal.ps1 -Execute
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_video_ab.ps1 -Execute -Input "C:\path\to\clip.mp4"
```

The real-video A/B defaults to 16 frames beginning at source frame 30 and
compares a persistent temporal session against an all-reset control. These
commands refresh the pinned runtime/static audit and Defender preflight before
native execution. They are developer hardware gates, not ordinary pytest or
normal application startup.

