# DLSS5 / MFG quality-performance experiment — 2026-09-20

Branch: `exp/dlss5-mfg-quality-performance`

This work is intentionally isolated from `main`. The validated C55/grid1
DLSS-G path and existing DLSS5 defaults remain the control configuration until
the experiments below pass ordinary CI and RTX 3070 Ti hardware review.

## DLSS5 changes under test

### Reduced-resolution NR

The existing residual-recomposition path now accepts an additional 87.5% work
scale and an `Auto` policy. Auto is deterministic for the render session: it
selects the highest supported work scale whose neural workload is at or below
approximately 1280x720 pixels. It does not oscillate frame by frame.

The application default remains 100%.

### Temporal residual stabilization

`src/backends/dlss5_quality.py` adds scene-reset-aware temporal stabilization
of the neural residual:

```text
current_residual = neural_output - source
stable_residual = blend(current_residual, warp(previous_stable_residual))
output = source + stable_residual
```

Only the neural residual is accumulated. The source frame remains the spatial
and motion anchor. History is discarded when the normal DLSS5 scene-reset
signal is raised. The default strength is 0, so existing v3 output is unchanged.

### Color and tone preservation

The experimental compositor can independently reduce neural chroma changes and
remove broad luma/tone shifts while retaining local neural structural edits.
Defaults are full neural color and no tone preservation, matching the existing
path.

### v10 native controls

The isolated v10 protocol already carried NR passes, color/tone controls,
face/skin protection, grain preservation, shimmer suppression, and NVOF
preference. The application façade, CLI, and WebUI now expose those fields
without changing the versioned native ABI.

The previous v10 defaults are retained: one pass, full color, no tone/face/grain
preservation, shimmer suppression 0.70, NVOF preference off.

### Transport work

The v3 and v10 video paths now use reusable `bytearray` + `readinto` decode
buffers rather than allocating and copying a new Python frame buffer for every
decoded frame. Render reports include decode, backend/native, and encoder-write
timing.

This is not a claim of a fully GPU-resident pipeline. The current v10 protocol
explicitly uses `memory_type=host`, and both application paths still feed
FFmpeg/NVENC through a host raw-video boundary. A true NVDEC/D3D12/CUDA ->
Feature 18 -> GPU composition -> NVENC path requires a separately validated
native transport/encoder contract. The new timing fields are intended to show
whether that larger redesign is justified and where its boundary should be.

## DLSS5 hardware matrices

### v3 matrix

```powershell
python tools\benchmark_dlss5_quality.py --input C:\path\to\owned-video.mp4
```

The bounded matrix compares:

- 100%, Auto, 87.5%, 75%, 67%, and 50% neural work scales;
- temporal residual stabilization at 0.25 / 0.50 / 0.75;
- a detail/tone-preserved composition;
- per-stage timing;
- source-effect MAE;
- motion-compensated neural-residual flicker MAE;
- synchronized review videos and raw-output hashes.

### v10 matrix

After the normal explicit v10 preflight:

```powershell
python tools\benchmark_dlss5_v10_quality.py --input C:\path\to\owned-video.mp4
```

The matrix compares the existing v10 default against:

- shimmer suppression off / 0.35 / 1.0;
- 2 / 3 / 4 NR passes;
- detail/tone preservation;
- optional NVIDIA Optical Flow preference when `--include-nvof` is supplied.

No result automatically changes the UI defaults.

## MFG 0.3.5 research boundary

Current upstream `sdli1995/dlssg_for_sm86` was reviewed at commit
`9621db573e07ed54f50c15bbb585ed9a7bdfac28` (0.3.5).

Relevant upstream findings:

- `Optimized=1` is documented as the output-preserving tier using rewritten
  kernels, cross-kernel fusions, and image-kernel patches;
- 0.3.3 stopped enabling `SkipRepeatedRealCopy` by default after flicker
  feedback;
- 0.3.4 narrowed the architecture rewrite so NVIDIA's own NGX/model components
  see the real GPU architecture;
- 0.3.5 invalidates stale optimized-kernel bindings when feature/kernel handles
  are recycled;
- upstream 0.3.x is a game-facing proxy architecture, while this project's
  validated C55 worker requires the older direct-host NGX-export contract.

Therefore the 0.3.5 proxy is **not** substituted for the validated runtime.

At the pinned public commit, repository code search exposes the optimization
contract/configuration and the proxy binary identity, but did not expose a
source implementation of the 63 optimized kernel variants/fusions that can be
adapted into this project's direct-host worker. The upstream project describes
its project source as GPLv3 while extracted/recompiled NVIDIA kernel resources
retain separate upstream terms. No upstream optimization implementation or
binary payload has been copied into this MIT repository.

`tools/audit_dlssg_sm86_035.py` performs a no-execution identity/configuration
audit for a locally supplied copy. It pins the exact Git blobs for the 0.3.5
`version.dll` and factory INI and requires `Optimized=1`,
`MaxGeneratedFrames=3`, and bundled-runtime mode.

It does not load the DLL.

## MFG hardware work

### C55 vs managed grid4, 2X / 3X / 4X

```powershell
python tools\benchmark_dlssg_grid4_matrix.py --input C:\path\to\owned-video.mp4 --encoded
```

For each multiplier, this records the pinned C55/grid1 baseline and managed
grid4 candidate with:

- no-encode raw sink SHA-256;
- native total / GPU wait / readback / NVOF timings;
- RPC/IPC gap;
- frame-count and interpolation-disable checks;
- device-removal checks;
- VRAM sampling;
- optional NVENC end-to-end timing.

Grid4 remains experimental regardless of a single passing matrix.

### Feature-recreation determinism

```powershell
python tools\validate_dlssg_recreation_soak.py --input C:\path\to\owned-video.mp4 --profile validated --multiplier 4 --cycles 15
python tools\validate_dlssg_recreation_soak.py --input C:\path\to\owned-video.mp4 --profile grid4-gpu-candidate --multiplier 4 --cycles 15
```

Each cycle starts a fresh worker process, creates exactly one new feature,
renders the same bounded input into a raw no-encode sink, closes, and requires
the sink hash to remain identical across all cycles.

This project deliberately uses process isolation instead of recreating an
optimized feature inside one long-lived proxy process. The soak proves that
project-specific contract; it does not claim that upstream in-process proxy
recreation is equivalent.

## Promotion gates

Nothing in this branch should replace the validated defaults until all of the
following are true:

1. ordinary CI is green;
2. the v3 and v10 quality matrices run cleanly on the RTX 3070 Ti;
3. review videos show no unacceptable text/face/edge/scene-cut regressions;
4. C55 and grid4 2X/3X/4X matrices complete without device removal or
   interpolation disable;
5. both MFG recreation soaks produce one stable sink hash per profile;
6. any proposed default change is made in a separate, reviewable commit after
   the evidence is checked.

Broader GPU coverage is intentionally deferred until additional hardware is
available.
