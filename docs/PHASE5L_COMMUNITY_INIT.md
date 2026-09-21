# Phase 5L — Community Runtime Initialization

## Primary result

`COMMUNITY_INIT_WORKING`

The previously missing boundary was implemented and invoked exactly once. The
community `NVSDK_NGX_D3D12_Init` export returned success using the actual RTX
3070 Ti D3D12 device and the official NGX-style Project-ID initialization
arguments. CreateFeature, EvaluateFeature, and ReleaseFeature were not called
in this narrow phase.

## A. Previous misclassification

Phase 5K reported `RUNTIME_INIT_FAILED`, but no community initialization call
had occurred there. It was an implementation gap, not an observed runtime
failure. Phase 5L replaces that conclusion with an actual result.

## B. Init ABI and implementation

- Source: `native\dlssg_sm86_offline\dlssg_sm86_offline.cpp`
- Mode: `--community-init-probe <community-dll> <official-runtime-dir>`
- Export: `NVSDK_NGX_D3D12_Init`
- Export RVA: `0x20710`
- Function address in this run: `0x00007FF8E7160710`
- Typedef:
  `NVSDK_NGX_Result (NVSDK_CONV *)(const char*, NVSDK_NGX_EngineType, const char*, const wchar_t*, ID3D12Device*, const NVSDK_NGX_FeatureCommonInfo*, NVSDK_NGX_Version)`

This is the public NVIDIA D3D12 Project-ID Init signature, selected because the
exact community export name and Phase 5G static argument analysis match it.

## C. Exact arguments

| Argument | Value |
|---|---|
| Project ID | `f8a17d65-4f1e-4e82-b0f2-4f6f93a7c8c1` |
| Engine type | `NVSDK_NGX_ENGINE_TYPE_CUSTOM` |
| Engine version | `1.0` |
| Application data path | `C:\Users\<user>\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere\_bin` |
| D3D12 device | `0x0000022C4D17DE10` |
| Feature info | official `NVSDK_NGX_FeatureCommonInfo` with the official runtime directory |
| SDK version | `NVSDK_NGX_Version_API` |

The parameter object was allocated by official NGX before community Init:

```text
PARAM_OBJECT_ALLOCATED result=0x00000001 ptr=0000022C63DA5F60
```

## D. Actual execution trace

```text
PROCESS_ENTRY
ARGS_PARSED
NGX_SHUTDOWN_SKIPPED_KNOWN_HANG=1
DXGI_ADAPTER_SELECTED=NVIDIA GeForce RTX 3070 Ti
D3D12_DEVICE_CREATED=1
NVAPI_LUID_MATCHED=1
NVAPI_NATIVE_ARCH=0x170
OFFICIAL_NGX_INIT_COMPLETE result=0x00000001
PARAM_OBJECT_ALLOCATED result=0x00000001 ptr=0000022C63DA5F60
COMMUNITY_LOAD_STARTED
COMMUNITY_LOAD_COMPLETE module=00007FF8E7140000
COMMUNITY_INIT_EXPORT_RESOLVED=00007FF8E7160710
COMMUNITY_INIT_STARTED
COMMUNITY_INIT_FUNCTION=NVSDK_NGX_D3D12_Init
COMMUNITY_INIT_ADDRESS=00007FF8E7160710
COMMUNITY_INIT_DEVICE_PTR=0000022C4D17DE10
COMMUNITY_INIT_RETURNED result=0x00000001
FINAL_RESULT=SUCCESS
```

The isolated child exited with code `0` within the 20-second watchdog. There
was no crash or hang at the community Init boundary.

## E. GPU and safety

- GPU: `NVIDIA GeForce RTX 3070 Ti`
- Driver: `610.62`
- Full DXGI/NVAPI LUID match: `1`
- Native architecture: `0x170`
- Community DLL SHA-256:
  `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- Community GPU generation attempts: `0`
- Swapchain: `0`
- Present: `0`
- Explicit NGX shutdown: skipped due known hang

Post-run `nvidia-smi`:

`NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 725 MiB, 39 C, 24%`

No driver/provider/system settings were changed. No GPU reset or TDR was
observed. No new Event 153 was observed.

## F. Scope limit

This phase intentionally stopped after proving Init. It did not claim direct
2X generation, output ownership, fence completion, or readback.

Next step: `IMPLEMENT_CREATE_EVALUATE_READBACK`.

## G. Git

- No commit.
- No push.
