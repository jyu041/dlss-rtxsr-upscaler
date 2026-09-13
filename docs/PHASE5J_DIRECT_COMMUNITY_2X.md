# Phase 5J — Direct Community Runtime Attempt

## Primary result

`RUNTIME_INIT_FAILED`

The official NGX parameter probe was made usable under the Phase 5J teardown
policy: it passes the actual RTX 3070 Ti identity, native architecture, typed
Set/Get checks, and resource-pointer round-trip, then exits the isolated probe
without calling the known-hanging NGX shutdown path. The assessed community
DLL also loaded directly and exposed the expected entry points.

The direct host did not yet contain a complete community initialization,
resource submission, Create, Evaluate, fence, and readback implementation.
Consequently no community Create/Evaluate GPU attempt was made. This is an
implementation boundary, not a generation failure.

## A. Baselines

- Primary HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community HEAD: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Community binary:
  `C:\Users\mark\Desktop\dlss-community-research\dlssg_for_sm86\version.dll`
- Size: `15,667,520` bytes
- SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- NVIDIA header snapshot: `374959484e79a640feaba44c93ac8cfb0a03f5b5`
- Official runtime directory:
  `C:\Users\mark\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere\_bin`

## B. GPU and official parameter object

- DXGI: `NVIDIA GeForce RTX 3070 Ti`
- Vendor: `0x10DE`
- Device: `0x2482`
- Full LUID: high `0x00000000`, low `0x0000D82F`
- NVAPI full-LUID match: `1`
- Native architecture: `0x170`
- NVAPI implementation: `0x4`
- Official NGX init: `0x00000001`
- Official capability-parameter allocation: `0x00000001`
- Scalar Set/Get: pass
- D3D12 resource-pointer Set/Get: pass
- Parameter vtable owner: `_nvngx.dll` from the installed NVIDIA driver

The parameter probe logged `PARAM_PROBE_PASS=1` and exited with code `0`
without calling `NVSDK_NGX_D3D12_Shutdown1`, as explicitly required for this
phase. The known shutdown hang remains separately documented.

## C. Community runtime probe

The exact assessed file was loaded explicitly by absolute path, not installed
as a proxy and not renamed:

```text
COMMUNITY_LOAD_STARTED
COMMUNITY_LOAD_COMPLETE
COMMUNITY_MODULE_BASE=00007FF910510000
CREATE_EXPORT=00007FF9105305D0
EVALUATE_EXPORT=00007FF910530630
RELEASE_EXPORT=00007FF9105307B0
INIT_EXPORT=00007FF910530710
ABI_CLASS=PUBLIC_NGX_ABI_WITH_THIN_ADAPTER
RUNTIME_PROBE_PASS=1
```

The process exited `0`. No unexpected child process, persistence, network, or
system configuration behavior was observed during this short load-only probe.

## D. Direct generation status

- Community initialization: **NOT IMPLEMENTED/NOT RUN**
- D3D12 command queue/list for community path: **NOT CREATED**
- caller-owned `OutputInterpolated`: **NOT CREATED**
- CreateFeature: **NOT RUN**
- reset Evaluate: **NOT RUN**
- measured Evaluate: **NOT RUN**
- queue submit/fence: **NOT RUN**
- readback: **NOT RUN**
- swapchain: `0`
- Present: `0`
- community GPU attempts: `0`
- retries: `0`

No output hash or image file exists because no generation was submitted.

## E. Build and selftest

Added the focused host files:

- `native\dlssg_sm86_offline\dlssg_sm86_offline.cpp`
- `native\dlssg_sm86_offline\build.ps1`
- `native\dlssg_sm86_offline\README.md`

x64 MSVC Release build passed with `/O2 /EHsc /W4 /Zi /MD`; the only warning
was an unreachable-code warning after the intentional `ExitProcess` probe
termination. Selftest passed:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
```

Exit code: `0`. Selftest did not load NGX, NVAPI, D3D12, or the community DLL.

## F. GPU health and safety

After the probes, `nvidia-smi` reported:

`NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 735 MiB, 39 C, 15%`

No NVIDIA/provider files, registry settings, HAGS, TDR, clocks, voltage, or
power limits were changed. No GPU reset occurred. No direct-generation attempt
means no new generation-related Event 153 was produced.

## G. Next step

`FIX_DIRECT_GENERATION_BOUNDARY`

Implement the missing direct community initialization and one-shot D3D12
Create/Evaluate/readback path before authorizing the single community GPU
attempt. Do not retry this phase with alternate binaries or runtimes.

## H. Git

- No commit.
- No push.
