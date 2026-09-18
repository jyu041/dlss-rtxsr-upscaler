# DLSS5 Visual Enhancer v10 Static ABI Audit — 2026-09-18

This document records the source-level ABI contract implemented on the research
branch. No Visual Enhancer v10 DLL has been loaded or executed by this project.

## Upstream source identity

Source state audited:

`Merserk/dlss5-visual-enhancer@7781107b89057f4d62d7c0a35fc3c1e90e7d9c31`

Release archive already pinned in the runtime manifest:

- `Visual.Enhancer.v10.0.zip`
- size: `690203043` bytes
- SHA-256:
  `394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515`

## Bridge ABI

The current Neural Rendering bridge reports frame ABI version **6**.

The project now encodes the observed ctypes-compatible layouts in
`src/backends/dlss5_v10_contract.py` without loading a DLL.

Observed structure sizes on the Windows/x64 ABI:

| Structure | Size |
|---|---:|
| `FrameDescriptorV1` | 88 bytes |
| `RenderParametersV3` | 72 bytes |
| `RenderParametersV4` | 80 bytes |
| `RenderParametersV5` | 88 bytes |
| `RenderParametersV6` | 96 bytes |
| `FrameResultV1` | 56 bytes |

ABI 6 extends the prior control prefix with:

- `nr_passes`;
- `shimmer_suppression`;
- `prefer_nvof`.

The frame descriptor supports:

- host memory;
- CUDA memory;
- no-memory sentinel;
- RGBA8;
- NV12;
- P010;
- up to three planes plus per-plane strides;
- color matrix/range/rotation metadata;
- a frame timestamp.

## Required bridge export surface

The project currently requires static evidence for these v10 bridge exports:

- `dlss5nr_version`
- `dlss5nr_gpu_name`
- `dlss5nr_adapter_luid`
- `dlss5nr_frame_abi_version`
- `dlss5nr_init`
- `dlss5nr_rebind`
- `dlss5nr_process_v6`
- `dlss5nr_process_cuda_v6`
- `dlss5nr_cuda_supported`
- `dlss5nr_cuda_status`
- `dlss5nr_process_frame_v6`
- `dlss5nr_temporal_status`
- `dlss5nr_scene_score_v1`
- `dlss5nr_surface_create`
- `dlss5nr_surface_frame_desc`
- `dlss5nr_surface_retain`
- `dlss5nr_surface_release`

`dlss5nr_release_session` is treated as optional because upstream resolves it
with `getattr`.

This list is the **minimal ABI-6 surface required by the project's proposed
adapter**, derived from the upstream ctypes binding. Upstream also binds legacy
entry points for compatibility; those older entry points are not required by
the proposed ABI-6-only adapter. This is not an NVIDIA public API claim.

The project now records the exact symbolic argument/return signatures for every
required entry point in `EXPORT_SIGNATURES`. In particular:

- `dlss5nr_init(int, wchar*, char*, int) -> int`
- `dlss5nr_process_v6(float*, float*, int, int, RenderParametersV6*, char*, int) -> int`
- `dlss5nr_process_cuda_v6(uint64, uint64, int, int, uint64, RenderParametersV6*, char*, int) -> int`
- `dlss5nr_process_frame_v6(FrameDescriptorV1*, FrameDescriptorV1*, RenderParametersV6*, FrameResultV1*, char*, int) -> int`

The CUDA capability/status exports are also mandatory because the upstream
binding resolves them directly rather than via an optional `getattr`.

## Lifetime semantics

Upstream treats the D3D12/NGX bridge as process-lifetime state.

Normal logical session close does not call
`NVSDK_NGX_D3D12_Shutdown` and does not unload driver modules because upstream
reports those operations can wedge after a successful Feature-18 evaluation.

A future project adapter must therefore not reuse the v3 teardown assumptions.

## Scale semantics

v10 source explicitly performs Lanczos resize **before** Neural Rendering.

- 25%, 50%, 75%: pre-downscale, then Feature 18.
- Source: native source dimensions, then Feature 18.
- 125%, 150%, 175%, 200%: pre-upscale, then Feature 18.

Therefore 125–200% is not evidence of native >1.0x Feature-18 output scaling on
Ampere. The existing v3 RTX 3070 Ti result—1.0x valid, higher native output
scale rejected with `0xBAD00005`—is not superseded by v10's UI scale controls.

## Fail-closed static project boundary

`src/backends/dlss5_v10_static.py` now performs a non-executing candidate
inspection.

It requires:

1. all three expected runtime DLLs;
2. valid x86_64 PE images;
3. the required ABI-6 bridge exports;
4. exact extracted-file hashes once those hashes are pinned.

Without pinned extracted hashes it returns `STATIC_IDENTITY_REQUIRED`.

Even after hashes and ABI checks pass it returns
`execution_allowed=False`.

This is deliberate: static evidence is necessary but not sufficient for a
native execution adapter.

## PE inspection

`src/core/pe_static.py` reads PE metadata from raw bytes only.

It records:

- machine architecture;
- PE32/PE32+ format;
- sections;
- imported DLL names;
- named exports.

The runtime candidate auditor now applies this automatically to extracted
`.dll` and `.exe` files. This lets us inspect likely networking/process
dependencies and ABI exports without `LoadLibrary`.

## Static networking / process-boundary review

The source-level Python bridge binding at the pinned v10 commit imports
`ctypes`, `contextlib`, `json`, `threading`, `time`, NumPy, path helpers,
and the NGX runtime lock. It contains no direct `subprocess`, `socket`,
`urllib`, `requests`, HTTP, `CreateProcess`, or `ShellExecute` references.

This is intentionally a **narrow bridge-source observation**. The Visual
Enhancer application as a whole includes legitimate process/network features
for FFmpeg, Live mode, source resolution, desktop integration, and media
handling. Those application-level features must not be attributed to the
Neural Rendering DLLs without binary evidence.

The project PE reader now records both imported DLL names and imported
functions/ordinals. The v10 static inspector flags direct networking or
process-launch imports as `STATIC_REVIEW_REQUIRED` even after exact hashes and
ABI checks pass. Absence of such direct imports is useful evidence but is not a
proof of no dynamic API resolution or runtime networking.

## Exact binary audit completed

The authentic v10 archive was successfully downloaded and statically audited on
a Windows GitHub Actions runner in research workflow run `35311872691`.

The workflow verified the pinned 690,203,043-byte archive SHA-256 before
extraction, extracted only the manifest allowlist, collected PE
imports/imported symbols/exports and Authenticode observations, asserted
`executed=false`, and uploaded only JSON evidence.

The three runtime DLL identities are now pinned:

- `nvngx_dlssnr.dll` — 165,830,144 bytes —
  `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927`
- `neuroframe_engine_neural_rendering.dll` — 571,904 bytes —
  `F657D20E569F97DEC25E02141F64354CD4B3E1DC51FA1DFE48ACEEBCC3CC43D5`
- `neuroframe_caller.dll` — 104,960 bytes —
  `B3611046837BC2F2E957A694CE0817E3C1B304BD653D0C7A193148E5BDD02437`

All are x86-64 PE32+ files. All three report Authenticode `NotSigned`.

Every required project ABI-6 bridge export is present. No one of the three
runtime DLLs directly imports Winsock/WinHTTP/WinINet/URLMon or
`CreateProcess*`/`ShellExecute*`/`WinExec`. Dynamic resolution functions
(`LoadLibrary*` / `GetProcAddress`) are present, so the direct-import result
must not be overstated as proof of no runtime dynamic resolution.

Full retained findings are in
`docs/DLSS5_V10_BINARY_STATIC_EVIDENCE_2026-09-18.md`.

## Promotion gate

After the exact extracted hashes/imports/exports/signatures are reviewed and
pinned, the next code stage is a **separate isolated v10 host/adapter**.

It must not replace `src/backends/dlss5.py` or the validated v3 path.

Only after that adapter passes compile-time/unit tests should one bounded
256x256 / one-frame / 1.0x RTX 3070 Ti test be considered.
