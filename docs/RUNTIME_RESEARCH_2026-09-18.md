# MFG 0.3.3 and DLSS5 v10 Research Gate — 2026-09-18

This document records the first implementation slice for the post-`3f481e75`
runtime-improvement phase. It is intentionally static-only: it does not change
the validated DLSS-G `legacy` default, does not execute the newer SM86 proxy,
and does not replace the validated DLSS5 v3 Feature-18 path.

## Baseline preserved

- Public baseline at branch creation:
  `3f481e75ae53eaf2f89cfb7000b7411c5f7cf96a`.
- DLSS-G normal profile remains `legacy`, using upstream
  `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40` plus NVIDIA provider 310.9.1.
- DLSS5 executable fallback remains the managed v3 Feature-18 path.
- No newer candidate is selected by `setup.bat`, `start.bat`, or the UI.

## DLSS-G / MFG candidate: sdli1995 0.3.3

Upstream:
`https://github.com/sdli1995/dlssg_for_sm86`

Release/tag:
`0.3.3`, published 2026-09-17.

Relevant upstream claims:

- 0.3.2 rewrote part of the 310.9 inference-kernel path.
- `Optimized=1` is claimed to be bit-identical to official DLSS-G output on
  the maintainer's tested hardware, with modest additional speed-up over the
  earlier optimized set.
- 0.3.3 disables `SkipRepeatedRealCopy` by default after a flicker report and
  moves architecture spoofing earlier for game/Streamline compatibility.
- The current package is proxy-oriented and embeds/matches an NVIDIA runtime;
  upstream explicitly reverted its earlier native/self-host direction because
  of game compatibility problems.

Classification:

- RTX 30/Ampere support is **community-enabled**, not official NVIDIA support.
- The release is interesting for performance/quality comparison, but its
  game-proxy architecture does not establish compatibility with this project's
  C55 direct-host worker.

### 0.3.3 direct-host stop condition

Further static review resolves the key compatibility question negatively for
the packaged proxy itself.

Upstream documents that:

- the first proxy whose `DllMain` runs becomes process-wide active;
- that active proxy installs a `LoadLibrary` hook;
- the proxy intercepts only the loading of `nvngx_dlssg.dll`;
- later proxy DLLs become forwarding-only standby instances;
- 0.3.0 deliberately reverted the upstream project from its native/self-built
  NGX-host direction back to this proxy architecture.

That lifecycle is materially different from the project C55 worker, which owns
its standalone direct-host initialization. The same architectural mismatch was
already observed with 0.3.1, and 0.3.3 has not changed that fundamental host
contract.

**Decision:** do not create an executable `candidate-0.3.3` C55 profile and do
not ask for an RTX 3070 Ti compatibility run of the proxy DLL itself. Static
analysis has already exhausted that path.

Exact 0.3.3 file SHA-256/size and signature evidence would still be required if
the project later stages the proxy for forensic comparison, but those identities
would not by themselves make it a direct-host candidate.

The actionable 0.3.3 research paths are instead:

1. treat its optimized-kernel/backend work as a reference for a separately
   adapted direct-host implementation, subject to license and binary-boundary
   review; or
2. leave the runtime unchanged and pursue the project's larger GPU-residency
   bottlenecks first.

If a future adapter actually exposes a C55-compatible direct-host boundary, it
must start again at the bounded 256x256 Create/reset and 2X/3X/4X external
motion + NVOF matrix before any practical-resolution test.

The validated `legacy` profile remains the fallback throughout.

## DLSS5 candidate: Visual Enhancer v10

Upstream:
`https://github.com/Merserk/dlss5-visual-enhancer`

Release:
`v10.0`, published 2026-09-17.

Pinned release asset:

- `Visual.Enhancer.v10.0.zip`
- size: `690203043` bytes
- SHA-256:
  `394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515`
- source commit observed for the v10 application state:
  `7781107b89057f4d62d7c0a35fc3c1e90e7d9c31`

The current upstream source describes the Neural Rendering path as an in-process
D3D12/NGX Feature-18 runtime with:

- `bin/runtime/dlssnr/nvngx_dlssnr.dll`
- `bin/runtime/dlssnr/neuroframe_engine_neural_rendering.dll`
- `bin/runtime/dlssnr/neuroframe_caller.dll`

This is materially different from the validated v3 package's
ReShade/RenoDX-style five-file execution environment.

Further source audit of v10 establishes:

- bridge ABI version: `6`;
- Feature ID remains `18`;
- the bridge supports host and CUDA memory paths plus RGBA8/NV12/P010 frame
  descriptors;
- normal session close deliberately does **not** call
  `NVSDK_NGX_D3D12_Shutdown` or unload the driver modules because upstream
  reports those teardown operations can wedge after successful Feature-18
  evaluation;
- `neuroframe_engine_neural_rendering.dll` and `neuroframe_caller.dll` are
  identified by upstream as Merserk-owned components, while
  `nvngx_dlssnr.dll` remains NVIDIA runtime material;
- candidate staging therefore retains both
  `LICENSE-Merserk.txt` and `LICENSE-NVIDIA-DLSS.txt` alongside the three
  DLLs.

The process-lifetime NGX policy is important for our adapter design: v10 must
not be dropped into the existing v3 lifecycle and assumed to have identical
shutdown semantics.

### v10 processing scale is now statically understood

The v10 source explicitly states that Feature 18 is evaluated at the final
Neural Rendering dimensions. Scale factors below 1.0 are Lanczos-downscaled
**before** Feature 18; scale factors above 1.0 (125%, 150%, 175%, 200%) are
Lanczos-upscaled **before** Feature 18.

Therefore the v10 125-200% controls are **not** evidence that Feature 18 exposes
a native >1.0x NGX output-scale mode on Ampere. They are a pre-resize plus
Neural Rendering workflow: the source image is first resized to the requested
final neural dimensions, then Feature 18 evaluates at that size.

This is still potentially useful for the project because a 2x final image could
be produced through conventional pre-upscale followed by Neural Rendering, but
it is architecturally different from the v3 higher-output-scale attempts that
returned NGX `InvalidParameter (0xBAD00005)`.

The current RTX 3070 Ti v3 evidence therefore still stands unchanged:

- 1.0x Feature-18 execution: validated.
- higher native v3 output scales: reproducible NGX
  `InvalidParameter (0xBAD00005)` / native fallback.

### v10 security and licensing gate

The v10 release is represented in the runtime manifest only as
`candidate-static-only`.

Before any execution:

1. validate the complete ZIP namespace;
2. extract only the three candidate Neural Rendering runtime files;
3. record exact extracted SHA-256 and size identities;
4. inspect PE imports/exports;
5. record Authenticode observations;
6. run Microsoft Defender over the staged payload;
7. determine whether the bridge/caller performs any networking;
8. document the in-process process boundary;
9. review the Merserk Source License 1.0 and third-party notices;
10. keep setup-time download pointed at the original upstream release rather
    than redistributing the v10 archive.

The v3 firewall rule remains specific to the v3 `nvngx.dll` worker and must not
be generalized to v10 until the v10 process boundary is understood.

### v10 execution ladder

If the static audit passes:

1. build a separate native adapter/host; do not modify the v3 backend contract;
2. run a bounded 256x256 single-frame native-size test;
3. prove Feature 18 is active and reject native fallback;
4. run a short temporal sequence with reset/cut coverage;
5. only then test 125/150/175/200% application processing scales;
6. record Feature-18 input/output geometry separately from final output geometry;
7. characterize VRAM, throughput, semantic drift, faces/materials/lighting, and
   temporal shimmer;
8. only after that consider exposing v10 as an executable experimental backend.

## Runtime-independent MFG work

The current project measurements show larger opportunities outside the
community inference kernel:

- NVOF execution is expensive at practical resolutions.
- NVOF flow becomes CPU-visible before conversion.
- color data is uploaded again for DLSS-G.
- the pipeline performs synchronous GPU waits and CPU-visible output transport.

The preferred future data path is:

`NVDEC -> GPU surface -> NVOF -> GPU flow conversion -> shared D3D12 DLSS-G resources -> GPU surface -> NVENC`

High-value engineering tasks before changing defaults:

1. D3D12 GPU timestamp queries around NVOF, flow conversion, resource copies,
   DLSS-G, and output transfer.
2. GPU-side S10.5 NVOF to R16G16 FP16 conversion.
3. persistent/shared color resources between NVOF and DLSS-G.
4. bounded asynchronous decode / FG / encode queues and explicit fences.
5. optional caller-supplied R32_FLOAT depth.
6. dissolve/fade-aware transition classification in addition to the existing
   hard-cut detector.
7. ground-truth interpolation validation using withheld frames from high-FPS
   source footage, with per-generated-index metrics for 2X/3X/4X.

## Promotion rule

Neither candidate may replace a validated path based on release recency or
upstream benchmark claims.

Promotion requires:

`stable fallback -> candidate identity/security -> static ABI/contract -> bounded synthetic -> RTX 3070 Ti hardware -> practical-resolution quality/performance -> explicit maintainer approval`
