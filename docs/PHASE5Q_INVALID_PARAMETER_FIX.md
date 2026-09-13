# Phase 5Q — Invalid-Parameter Correction

## A. Result decoding

Phase 5P returned `0xBAD00005`, which is
`NVSDK_NGX_Result_FAIL_InvalidParameter`. The Phase 5P subcause was therefore
`COMMUNITY_EVALUATE_INVALID_PARAMETER` at the bootstrap call.

## B. Contract comparison and identified correction

The Phase 5P host had three concrete contract defects before the retry:

1. It set generic `Width`/`Height` but omitted the distinct
   `DLSSG.Width`/`DLSSG.Height` keys required by the known worker.
2. Uploaded color/depth/motion textures remained in `COPY_DEST` instead of
   transitioning to `NON_PIXEL_SHADER_RESOURCE` before Evaluate.
3. `OUTPUT_DISABLE` was initially modeled as a texture rather than the
   required 4-byte UAV buffer.

The correction set both DLSS-G-specific dimensions to `256`, added the input
resource transition, replaced the disable resource with a 4-byte UAV buffer,
and added the required zeroing barrier/copy sequence before bootstrap.

These are objective mismatches against the public helper/known worker contract;
they were not speculative parameter tweaks.

## C. Build and selftest

- Primary HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community commit: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Build: PASS, x64 MSVC 19.44.35228, `/O2 /EHsc /W4 /Zi /MD`
- Selftest: PASS, exit code `0`

Trace:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
```

## D. Corrected retry

Exactly one corrected retry was executed:

```text
C:\Users\mark\Desktop\dlss-rtxsr-upscaler\native\dlssg_sm86_offline\bin\dlssg_sm86_offline.exe --run-2x C:\Users\mark\Desktop\dlss-community-research\dlssg_for_sm86\version.dll C:\Users\mark\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere\_bin
```

Attempts: `1`; retries: `0`.

The run reached D3D12 device/queue creation and community Init, but stopped at
the first input upload call with exit code `39`. No `DLSSG_WIDTH` marker was
reached, CreateFeature was not called in this retry, and neither bootstrap nor
measured Evaluate was called. Consequently the original `0xBAD00005` was not
reproduced or disproved by this run.

Trace:

```text
PROCESS_ENTRY
ARGS_PARSED
SWAPCHAIN_USED=0
PRESENT_USED=0
PARAM_OBJECT_PROVENANCE=OFFICIAL_NVIDIA_NGX
FEATURE_IMPLEMENTATION=COMMUNITY_SM86_RUNTIME
GPU_IDENTIFIED=NVIDIA_VID_0x10DE LUID=00000000:0000D82F
D3D12_CREATED=1
QUEUE_CREATED=1
NGX_INIT_STARTED
NGX_INIT_RESULT=0x00000001
EVALUATE_EXPORT_NAME=NVSDK_NGX_D3D12_EvaluateFeature
EVALUATE_EXPORT_ADDRESS=00007FF8E7160630
COMMUNITY_INIT_RESULT=0x00000001
```

The first actual remaining failure is the upload stage represented by the
existing exit code `39`; the current implementation does not emit a finer
upload substage marker.

## E. GPU and safety

Before:

```text
NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 666 MiB, 40 C, 19 %
```

After:

```text
NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 672 MiB, 40 C, 22 %
```

No matching nvlddmkm, Display, WHEA, Application Error, or WER events were
found in the narrow window. New Event 153: `NO`.

No provider/driver files or system settings were modified. No swapchain or
Present was used. Community Evaluate calls: `0` in the corrected retry.

## F. Primary result

`EVAL_PARAMETER_CAUSE_NOT_IDENTIFIED`

The parameter correction was concrete, but the retry failed before Create and
Evaluate, so it cannot yet establish whether the original invalid-parameter
failure is resolved.

## Next step

`FIX_EXACT_FIRST_EVALUATE_FAILURE`

The next run would need to fix the upload-stage failure first; no further run
was made in this phase.

## Git

- No commit.
- No push.
