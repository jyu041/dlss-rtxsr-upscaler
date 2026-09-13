# Phase 5K — Direct Community 2X Implementation Boundary

## Primary result

`RUNTIME_INIT_FAILED`

Phase 5K did not reach a valid community generation attempt. The official
parameter-object preflight and direct community export probe pass, but the
host still lacks the complete direct community initialization/resource/
Create/Evaluate/fence/readback path. No malformed or partial GPU call was
submitted.

## A. Existing implementation

The focused host remains under:

- `native\dlssg_sm86_offline\dlssg_sm86_offline.cpp`
- `native\dlssg_sm86_offline\build.ps1`
- `native\dlssg_sm86_offline\README.md`

Implemented and verified:

- x64 MSVC build with `/W4 /Zi`
- GPU-free `--selftest`
- actual RTX 3070 Ti selection
- full DXGI/NVAPI LUID match
- native architecture `0x170`
- official NGX initialization
- official parameter allocation
- scalar Set/Get
- D3D12 resource-pointer Set/Get
- shutdown-skip parameter probe exit
- exact community DLL direct LoadLibrary export probe

Not implemented as a complete operational path:

- community initialization bound to a live execution host
- uploaded synthetic Frame A/Frame B resources
- complete DLSS-G parameter population
- community Create/Evaluate lifecycle
- command-list submission and fence synchronization
- output transition/readback/statistics

## B. Baselines

- Primary HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community HEAD: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Community DLL: `C:\Users\mark\Desktop\dlss-community-research\dlssg_for_sm86\version.dll`
- Community DLL SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- Header snapshot: `374959484e79a640feaba44c93ac8cfb0a03f5b5`

## C. Preflight evidence

The official parameter probe passed on the target machine:

- GPU: `NVIDIA GeForce RTX 3070 Ti`
- vendor: `0x10DE`
- device: `0x2482`
- full LUID: high `0x00000000`, low `0x0000D82F`
- NVAPI match: `1`
- native architecture: `0x170`
- official NGX init: `0x00000001`
- parameter allocation: `0x00000001`
- typed/resource round-trips: pass
- probe exit: `0`

The exact community DLL load-only probe also passed:

```text
COMMUNITY_LOAD_COMPLETE
CREATE_EXPORT=00007FF9105305D0
EVALUATE_EXPORT=00007FF910530630
RELEASE_EXPORT=00007FF9105307B0
INIT_EXPORT=00007FF910530710
ABI_CLASS=PUBLIC_NGX_ABI_WITH_THIN_ADAPTER
RUNTIME_PROBE_PASS=1
```

## D. Community generation

- community initialization result: **NOT RUN**
- CreateFeature: **NOT RUN**
- reset Evaluate: **NOT RUN**
- measured Evaluate: **NOT RUN**
- caller-owned OutputInterpolated: **NOT CREATED**
- queue/fence: **NOT RUN**
- readback/output: **NOT RUN**
- swapchain: `0`
- Present: `0`
- community GPU attempts: `0`
- retries: `0`

There is no valid Create/Evaluate result or output hash to report. The
Phase 5I NGX shutdown hang remains handled by the approved skip policy; no NGX
shutdown call was made in the passing parameter probe.

## E. GPU health and safety

The post-probe GPU remained responsive:

`NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 735 MiB, 39 C, 15%`

No driver/provider files, registry, HAGS, TDR, VBIOS, clock, voltage, or power
settings were changed. No community generation work was submitted.

## F. Next step

`FIX_ACTUAL_RUNTIME_FAILURE`

Complete the direct community host’s initialization and resource/fence/
readback implementation before authorizing the single community GPU attempt.
Do not retry with alternate runtimes or providers.

## G. Git

- No commit.
- No push.
