# Architecture

`app.py` launches the localhost Gradio application. The UI is intentionally
split into three workspaces:

- **Enhance** — upload, backend selection, settings, preview, render, progress;
- **Configuration** — backend readiness, Runtime Manager, experimental
  preflights, reusable presets;
- **Diagnostics** — local CPU/RAM/GPU/VRAM telemetry and implementation notes.

The major source packages are:

- `src/core/` — paths, settings, diagnostics, job ownership, progress, media
  inspection, and shared application state;
- `src/video/` — FFmpeg-facing decode/encode/mux pipelines and backend-specific
  video orchestration;
- `src/backends/` — strict adapters/clients for RTX VSR, DLSS SR, DLSS-G,
  DLSS 5 v3, and DLSS 5 v10;
- `src/runtime_manager/` — manifest-driven download, extraction, identity,
  activation, verification, and repair policy.

## Backend boundaries

### RTX VSR

RTX VSR processes frames through NVIDIA's VFX Python package. Availability is
hardware/driver/package dependent and is checked independently of the other
backends.

### DLSS Super Resolution

DLSS SR uses a separate native D3D12/NGX host with persistent per-job state and
estimated optical-flow motion guidance. It does not receive game-engine motion
vectors, depth, or jitter. The managed host/runtime identity is verified before
use and a local self-test is available from Configuration.

### DLSS Frame Generation

DLSS-G uses the project worker plus the validated SM86 direct-host runtime and
official NVIDIA provider. The normal path is the pinned C55/grid1 profile.
The separately pinned grid4/GPU-resident NVOF worker is exposed only as an
explicit experimental profile; it does not replace the default.

### DLSS 5 v3

The v3 Feature-18 path is optional and experimental. It requires a separately
approved local runtime, exact hashes, Defender evidence, an exact outbound
firewall rule, and a successful Feature-18 self-test before the backend can
become ready.

### DLSS 5 v10 Experimental

v10 is separate from v3. Its generic legacy host entry point remains disabled;
the application uses a separately acknowledged experimental application path.
That path requires pinned archive/runtime identity, fresh preflight/Defender
evidence, isolated child execution, temporary outbound firewall containment,
process-tree checks, per-frame NGX/CUDA/timestamp/geometry/reset validation,
scene-aware resets, and clean CLOSE/cleanup.

The current application boundary is SDR RGBA8, 1.0x processing/output geometry,
and up to 1920x1080-equivalent input.

## Runtime model

Normal source setup provisions managed components into ignored `runtime/`
paths. Runtime Manager records the public source URL, archive/file identity,
destination, and verification policy for each managed component.

Generated runtimes, approvals, logs, previews, temporary files, outputs, and
user media remain outside the tracked source tree.

Each backend is independently gated. Missing runtimes, identity mismatches,
failed self-tests, or failed security gates stop that backend operation rather
than falling back to another enhancer.
