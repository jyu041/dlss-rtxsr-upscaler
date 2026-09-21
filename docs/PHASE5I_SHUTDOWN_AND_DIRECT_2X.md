# Phase 5I — NGX Shutdown Isolation

## Primary result

`NGX_SHUTDOWN_HANG`

The Phase 5H parameter-object conclusion was corrected. On the actual RTX
3070 Ti, official NGX initialization, parameter allocation, scalar Set/Get, and
D3D12-resource pointer round-trip all succeeded. The smallest reproducer for
the hang is simply official NGX initialization followed by
`NVSDK_NGX_D3D12_Shutdown1(device)`, without parameter allocation or any
feature creation. The community runtime was not loaded and no direct community
2X attempt was made.

## A. Baselines

- Primary HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community HEAD: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Community runtime SHA-256:
  `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- NVIDIA header snapshot: `374959484e79a640feaba44c93ac8cfb0a03f5b5`
- Official runtime directory:
  `C:\Users\<user>\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere\_bin`

## B. Exact shutdown call and smallest reproducer

The Phase 5H source used `NVSDK_NGX_D3D12_Shutdown1(device)`, where `device`
was the same `ID3D12Device*` passed to
`NVSDK_NGX_D3D12_Init_with_ProjectID`. The Phase 5I probe logged the exact
sequence:

```text
OFFICIAL_NGX_INIT_RESULT=0x00000001
NGX_TEARDOWN_STARTED
NGX_SHUTDOWN1_STARTED
```

`NGX_SHUTDOWN1_RETURNED` was never emitted within the 15-second bounded
shutdown probe. A second variant using `Shutdown1(nullptr)` also hung. The
hang therefore occurs before parameter allocation and is not caused by the
test resource, parameter Reset, parameter destruction, or a community ABI.

The init device pointer and shutdown device pointer were the same object in the
source; no pointer mismatch was introduced.

## C. Isolation results

| Lifecycle | Result |
|---|---|
| Init → Shutdown1(device) | hangs at shutdown entry |
| Init → Shutdown1(nullptr) | hangs at shutdown entry |
| Init → GetCapabilityParameters → typed Set/Get → Reset → Destroy → Shutdown1 | hangs at shutdown entry |

The complete parameter test reached:

```text
PARAM_TYPED_ROUNDTRIP=1
PARAM_RESOURCE_POINTER_MATCH=1
PARAM_RESET_COMPLETE
PARAM_DESTROY_COMPLETE
OFFICIAL_NGX_SHUTDOWN_STARTED
```

## D. Actual GPU and parameter object

- DXGI adapter: `NVIDIA GeForce RTX 3070 Ti`
- Vendor: `0x10DE`
- Device: `0x2482`
- LUID: high `0x00000000`, low `0x0000D82F`
- NVAPI full-LUID match: `1`
- Native architecture: `0x170`
- NVAPI implementation: `0x4`
- Official NGX init: `0x00000001`
- Capability-parameter allocation: `0x00000001`
- Parameter object: `0x000001BA5E848360` (representative run)
- Vtable: `0x00007FF91A354970`
- Vtable owner: `C:\WINDOWS\System32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\_nvngx.dll`
- Scalar Set/Get: pass
- D3D12 resource-pointer Set/Get: pass

## E. Build and selftest

Created the focused probe under:

- `native\dlssg_sm86_offline\dlssg_sm86_offline.cpp`
- `native\dlssg_sm86_offline\build.ps1`
- `native\dlssg_sm86_offline\README.md`

x64 MSVC Release build passed with `/O2 /EHsc /W4 /Zi /MD`. The GPU-free
selftest passed:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
```

Exit code: `0`.

## F. Community runtime and direct 2X

- Community `version.dll` LoadLibrary: **NO**
- Community initialization: **NOT RUN**
- CreateFeature: **NOT RUN**
- reset Evaluate: **NOT RUN**
- measured Evaluate: **NOT RUN**
- caller-owned output resource: **NOT CREATED**
- swapchain: `0`
- Present: `0`
- attempts: `0`
- retries: `0`

The Phase 5I instruction permits treating a pure teardown defect as non-
operational, but a direct community host was not yet implemented in the
focused probe and the official lifecycle remains unclosed. Proceeding to
community Create/Evaluate from this process would therefore not be a clean
controlled ABI test.

## G. GPU health and safety

Post-probe `nvidia-smi` remained responsive:

`NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 706 MiB, 39 C, 22%`

A narrow System/Application event query for the preceding 30 minutes returned
no matching `nvlddmkm`, `Display`, `WHEA`, Application Error, or WER events.
New `nvlddmkm` Event 153: **NO**.

No provider, driver, registry, HAGS, TDR, VBIOS, voltage, power, or clock
settings were changed. The watchdog terminated only the isolated probe process
after its shutdown timeout.

## H. Corrected conclusion and next step

The parameter object itself is compatible with the official public interface;
`OFFICIAL_PARAM_OBJECT_INCOMPATIBLE` is not the correct diagnosis. The exact
current blocker is an official NGX teardown hang present even in the minimal
Init → Shutdown1 lifecycle.

Next step: `FIX_EXACT_FAILURE_BOUNDARY`.

## I. Git

- No commit.
- No push.
