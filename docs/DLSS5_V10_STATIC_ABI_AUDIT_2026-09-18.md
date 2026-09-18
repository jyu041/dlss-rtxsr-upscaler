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
- `dlss5nr_process_frame_v6`
- `dlss5nr_temporal_status`
- `dlss5nr_scene_score_v1`
- `dlss5nr_surface_create`
- `dlss5nr_surface_frame_desc`
- `dlss5nr_surface_retain`
- `dlss5nr_surface_release`

`dlss5nr_release_session` is treated as optional because upstream resolves it
with `getattr`.

This list is an observed upstream application contract, not an NVIDIA public
API claim.

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

## Remaining static blocker

The authentic v10 release archive is pinned at archive level, but this
environment could not retrieve the ~690 MB GitHub release asset.

Therefore the exact extracted identities for:

- `nvngx_dlssnr.dll`;
- `neuroframe_engine_neural_rendering.dll`;
- `neuroframe_caller.dll`;
- `LICENSE-NVIDIA-DLSS.txt`;
- `LICENSE-Merserk.txt`;

remain to be generated from the authentic release archive using:

```powershell
python tools\audit_runtime_candidate.py dlss5-neuroframe-v10-static-candidate ^
  --archive C:\path\to\Visual.Enhancer.v10.0.zip ^
  --authenticode ^
  --output runtime\audit\dlss5-v10-static.json
```

This command extracts into temporary storage, records evidence, and executes no
candidate binary.

## Promotion gate

After the exact extracted hashes/imports/exports/signatures are reviewed and
pinned, the next code stage is a **separate isolated v10 host/adapter**.

It must not replace `src/backends/dlss5.py` or the validated v3 path.

Only after that adapter passes compile-time/unit tests should one bounded
256x256 / one-frame / 1.0x RTX 3070 Ti test be considered.
