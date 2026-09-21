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
  and the unified DLSS 5 facade over the preferred v10 runtime plus the retained
  v3 compatibility backend;
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

### DLSS 5

The application exposes one DLSS 5 mode. `DLSS5UnifiedBackend` selects the
isolated v10 application runtime whenever its explicit preflight is ready.
The validated v3 Feature-18 backend is retained only as an internal
compatibility fallback while v10 coverage is still being expanded; users do not
select a DLSS version.

The preferred v10 path keeps its existing security boundary: pinned
archive/runtime identity, fresh preflight/Defender evidence, isolated child
execution, temporary outbound firewall containment, process-tree checks,
per-frame NGX/CUDA/timestamp/geometry/reset validation, scene-aware resets, and
mandatory clean CLOSE/cleanup.

Around that v10 native session, the project now provides the shared application
pipeline that previously existed only on v3:

- deterministic Auto or fixed 100/87.5/75/67/50% neural working resolution;
- residual recomposition back onto the native-resolution source;
- CUDA-preferred or CPU recomposition;
- optional motion-compensated temporal stabilization of the neural residual;
- native v10 1–4 pass, color/tone, face/skin, grain, shimmer, and NVOF controls.

The validated native-input boundary remains SDR RGBA8 and up to
1920x1080-equivalent input. Reduced working resolution does not expand that
hardware-evidence boundary and does not change final output dimensions.

If the preferred runtime is not ready, the unified dispatcher may use the
validated v3 backend internally. Shared working-resolution, recomposition,
temporal, color, and tone controls remain available there. A non-default
v10-only control is never silently ignored: the render fails with an actionable
message instead.

## Runtime model

Normal source setup provisions managed components into ignored `runtime/`
paths. Runtime Manager records the public source URL, archive/file identity,
destination, and verification policy for each managed component.

Generated runtimes, approvals, logs, previews, temporary files, outputs, and
user media remain outside the tracked source tree.

Each enhancement family is independently gated. Missing runtimes, identity
mismatches, failed self-tests, or failed security gates stop that family rather
than substituting a different enhancer. Inside the single DLSS 5 family, the
validated v3 compatibility runtime may be selected when v10 is not ready; that
state is reported explicitly and v10-only settings are never silently ignored.
