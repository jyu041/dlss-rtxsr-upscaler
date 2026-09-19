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

## DLSS5 v10 research and experimental application gates

The normal/default v10 backend remains disabled. The validated research
sequence remains available, and the application exposes a separate explicit
`DLSS 5 v10 Experimental` mode rather than silently replacing v3:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_bounded.ps1 -Execute
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_temporal.ps1 -Execute
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_video_ab.ps1 -Execute -Input "C:\path\to\clip.mp4"
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_scene_cut.ps1 -Execute -Input "C:\path\to\clip.mp4"
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_scene_soak.ps1 -Execute -Input "C:\path\to\clip.mp4"
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_app_smoke.ps1 -Execute -Input "C:\path\to\clip.mp4"
```

Application-level hardware evidence is recorded in
[`DLSS5_V10_APP_HARDWARE_2026-09-19.md`](DLSS5_V10_APP_HARDWARE_2026-09-19.md).
On the RTX 3070 Ti, the exact UI renderer path passed both a 90-frame 640x480
smoke and a 30-frame 1920x1080 ceiling smoke at 1.0x. Both runs required the
fresh static/Defender preflight, isolated host, per-frame validation, clean
`CLOSED`, and firewall containment/cleanup before the wrapper emitted PASS.

The real-video A/B defaults to 16 frames beginning at source frame 30 and
compares a persistent temporal session against an all-reset control. The
scene-cut gate defaults to 32 frames beginning at frame 0 and fails if that
window contains no detected hard cut. It compares no-cut-reset, scene-aware
reset and all-reset control sessions. The 128-frame scene-aware soak compares
scene-aware reset against all-reset control and adds source-derived
motion-compensated temporal diagnostics while keeping those diagnostics outside
the native PASS/FAIL decision.

The soak also exports three synchronized MP4 review artifacts from the exact
in-memory frames used for the metrics:

- `source-sceneaware-reset-<scale>x.mp4`;
- `sceneaware-reset-<scale>x.mp4`;
- `sceneaware-reset-diff8x-<scale>x.mp4`.

The default review scale is 2x; `-ReviewScale 1`, `2`, or `4` can be
supplied to the PowerShell wrapper. The difference video amplifies the
scene-aware/reset absolute RGB difference by 8x. Review encoding occurs only
after both bounded native sessions have closed, so it is diagnostic artifact
generation rather than part of the native execution boundary. The wrapper
requires all three review videos and prints their paths explicitly.

The bounded research wrappers and the application smoke wrapper refresh the
pinned runtime/static audit and Defender preflight before native execution. The
application smoke runs the same `render_dlss5_v10()` path used by the UI for a
short clip and requires the exact `EXPERIMENTAL_APP_SCENE_AWARE_V10`
acknowledgement. The UI exposes a separate **Refresh DLSS 5 v10 preflight**
button before experimental rendering. Current application constraints are SDR
RGBA8, 1.0x processing scale, and up to 1920x1080-equivalent geometry.

These remain explicit developer/experimental paths, not ordinary pytest and
not an automatic replacement for DLSS 5 v3.

