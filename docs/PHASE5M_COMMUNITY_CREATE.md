# Phase 5M — Community CreateFeature

## Primary result

`COMMUNITY_CREATE_WORKING`

The exact community CreateFeature export was invoked once with the official
NVIDIA-created parameter object and a valid open D3D12 command list. It returned
success and a non-null feature handle. EvaluateFeature was intentionally not
called in this phase.

## A. Baseline

- Primary HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community HEAD: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Community DLL SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- Community DLL size: `15,667,520` bytes
- NVIDIA header snapshot: `374959484e79a640feaba44c93ac8cfb0a03f5b5`

## B. GPU and device

- DXGI adapter: `NVIDIA GeForce RTX 3070 Ti`
- Vendor: `0x10DE`
- Device: `0x2482`
- Full DXGI/NVAPI LUID match: `1`
- Native architecture: `0x170`
- D3D12 device: created
- D3D12 queue: created
- Command allocator: created
- Command list: created and open

## C. Official NGX and community Init

- Official NGX Init: `0x00000001`
- Official capability parameter allocation: `0x00000001`
- Parameter object: `0x0000021949666BF0`
- Community Init: `0x00000001`
- NGX shutdown policy: skipped due independently reproduced hang

## D. Create ABI

- Export: `NVSDK_NGX_D3D12_CreateFeature`
- Export RVA: `0x205D0`
- Runtime address: `0x00007FF8E71605D0`
- Typedef:
  `NVSDK_NGX_Result (NVSDK_CONV *)(ID3D12GraphicsCommandList*, NVSDK_NGX_Feature, const NVSDK_NGX_Parameter*, NVSDK_NGX_Handle**)`
- Feature ID: `NVSDK_NGX_Feature_FrameGeneration`
- Feature name: `FrameGeneration`

## E. Creation parameters

The official parameter object was populated and read back before the call:

- Width: `256`
- Height: `256`
- Internal width: `256`
- Internal height: `256`
- Backbuffer format: `DXGI_FORMAT_R8G8B8A8_UNORM` (`28`)
- Creation node mask: `1`
- Visibility node mask: `1`
- Dynamic resolution: `0`
- Round-trip: pass

## F. Actual Create execution

```text
PROCESS_ENTRY
ARGS_PARSED
NGX_SHUTDOWN_SKIPPED_KNOWN_HANG=1
SWAPCHAIN_USED=0
PRESENT_USED=0
DXGI_ADAPTER_SELECTED=NVIDIA GeForce RTX 3070 Ti
D3D12_DEVICE_CREATED=1
NVAPI_LUID_MATCHED=1
NVAPI_NATIVE_ARCH=0x170
D3D12_QUEUE_CREATED=1
COMMAND_ALLOCATOR_CREATED=1
COMMAND_LIST_CREATED=1
OFFICIAL_NGX_INIT_COMPLETE result=0x00000001
PARAM_OBJECT_ALLOCATED result=0x00000001 ptr=0000021949666BF0
COMMUNITY_LOAD_COMPLETE module=00007FF8E7140000
COMMUNITY_INIT_STARTED
COMMUNITY_INIT_RETURNED result=0x00000001
CREATE_PARAMETERS_POPULATED
CREATE_PARAM_WIDTH=256 HEIGHT=256 INTERNAL_WIDTH=256 INTERNAL_HEIGHT=256 FORMAT=28 DYNAMIC_RESOLUTION=0
COMMUNITY_CREATE_STARTED
CREATE_FUNCTION=NVSDK_NGX_D3D12_CreateFeature
CREATE_ADDRESS=00007FF8E71605D0
CREATE_CMDLIST_PTR=000002197539EFD0
CREATE_PARAM_PTR=0000021949666BF0
COMMUNITY_CREATE_RETURNED result=0x00000001
FEATURE_HANDLE=000002194977BD60
COMMUNITY_EVALUATE_CALLS=0
RELEASE_FEATURE_SKIPPED_PHASE5M=1
FINAL_RESULT=SUCCESS
```

Child exit code: `0` within the 30-second watchdog. Create attempts: `1`.
Retries: `0`.

## G. Presentation and output

- Swapchain used: `0`
- Present used: `0`
- Evaluate calls: `0`
- Output resource/readback: not yet performed

## H. GPU health

Before the Create probe:

`NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 703 MiB, 39 C, 20%`

After the Create probe:

`NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 692 MiB, 39 C, 21%`

A narrow System/Application event query found no matching `nvlddmkm`,
`Display`, `WHEA`, Application Error, or WER events. New Event 153: **NO**.

## I. Scope limit and next step

This proves the community Create boundary only. No frame data, Evaluate,
fence, or output readback was attempted.

Next step: `IMPLEMENT_EVALUATE_AND_OUTPUT_READBACK`.

## J. Git

- No commit.
- No push.
