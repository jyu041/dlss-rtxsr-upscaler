# Phase 5P — First Community DLSS-G Evaluate

## Primary result

`RESET_EVALUATE_FAILED`

The new direct host implementation reached the community Init and CreateFeature
boundaries, then made exactly one reset/bootstrap community Evaluate call. That
call returned `0xBAD00005`. The measured Evaluate was not called, and no output
readback was attempted. No retry was made.

## A. Baselines

- Primary HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Canonical community repository commit: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Community runtime: `C:\Users\mark\Desktop\dlss-community-research\dlssg_for_sm86\version.dll`
- Community runtime SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- Official runtime directory: `C:\Users\mark\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere\_bin`
- NVIDIA headers: local DLSS SDK include snapshot used by the existing host
- Community Evaluate calls: `1` (bootstrap only); measured calls: `0`

Prerequisites from prior phases remained established: community Init, community
CreateFeature, and the complete D3D12 resource upload/readback pipeline.

## B. Implementation

Added `native\dlssg_sm86_offline\community_run2x.cpp` and wired
`--run-2x <community-runtime> <official-runtime-directory>` into the existing
offline executable. The module uses an official `NVSDK_NGX_Parameter` object,
public DLSS-G parameter names, the proven 256x256 resource formats, one direct
queue, and the resolved community `NVSDK_NGX_D3D12_EvaluateFeature` export.

The executed binary was rebuilt with MSVC 19.44.35228, x64, `/O2 /EHsc /W4
/Zi /MD`. Build passed. Selftest passed with:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
```

## C. GPU and resources

- Adapter: NVIDIA GeForce RTX 3070 Ti
- Vendor: `0x10DE`
- DXGI LUID: `00000000:0000D82F`
- Native architecture: prior verified `0x170`
- D3D12 device: created
- Direct queue: created
- Resolution: 256x256
- Color: `R8G8B8A8_UNORM`
- Depth: `R32_FLOAT`
- Motion: `R16G16_FLOAT`
- OutputInterpolated: `R8G8B8A8_UNORM`, UAV-capable

The run used the official parameter object and logged:

```text
PARAM_OBJECT_PROVENANCE=OFFICIAL_NVIDIA_NGX
FEATURE_IMPLEMENTATION=COMMUNITY_SM86_RUNTIME
SWAPCHAIN_USED=0
PRESENT_USED=0
```

## D. Community feature

```text
NGX_INIT_RESULT=0x00000001
COMMUNITY_INIT_RESULT=0x00000001
CREATE_RESULT=0x00000001 HANDLE=000002105DC12F00
```

The handle was non-null. The resolved export was:

```text
EVALUATE_EXPORT_NAME=NVSDK_NGX_D3D12_EvaluateFeature
EVALUATE_EXPORT_ADDRESS=00007FF8E7160630
```

## E. Bootstrap Evaluate

The intended bootstrap contract was FrameID `0`, `reset=true`,
`multiFrameCount=1`, and `multiFrameIndex=1`, with Frame A color/depth/motion,
Frame A as HUDLess, caller-owned OutputInterpolated, and OutputDisable.

The actual stage trace was:

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
CREATE_STARTED
CREATE_RESULT=0x00000001 HANDLE=000002105DC12F00
BOOTSTRAP_EVALUATE_STARTED
BOOTSTRAP_EVALUATE_RESULT=0xBAD00005
```

The bootstrap command list was not submitted after the failed return. Therefore
there is no bootstrap fence result and no device-removal result to report.

## F. Measured Evaluate and output

- Measured Evaluate: not called
- Measured GPU submission: not made
- Output-disable readback: not attempted
- OutputInterpolated readback: not attempted
- Generated output file: none
- Output SHA/statistics: none

The required two-call sequence was stopped at the first actual failure, as
specified by the phase. No `EVALUATE_FAILED` or output classification is used
because the measured call was never reached.

## G. GPU health

Before:

```text
NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 707 MiB, 39 C, 21 %
```

After:

```text
NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 706 MiB, 40 C, 22 %
```

No matching `nvlddmkm`, Display, WHEA, Application Error, or WER events were
found in the narrow post-run window. New Event 153: `NO`.

## H. Teardown and safety

The process exited with code `46` at the bootstrap Evaluate failure. No NGX
shutdown call was made. No provider or driver file was modified. No swapchain,
Present, community prebuilt generation proxy, or unrelated-process injection was
used. Attempts: `1`; retries: `0`.

## Next step

`FIX_EXACT_FIRST_EVALUATE_FAILURE`

## Git

- No commit.
- No push.
