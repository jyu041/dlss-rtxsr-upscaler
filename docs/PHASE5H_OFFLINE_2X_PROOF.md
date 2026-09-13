# Phase 5H — Offline 2X Proof

## Primary result

`OFFICIAL_PARAM_OBJECT_INCOMPATIBLE`

The official NVIDIA parameter-object interoperability checks passed on the
actual RTX 3070 Ti, but the official NGX cleanup call hung and the probe could
not exit cleanly. The community runtime was therefore not loaded, and no
community Create/Evaluate attempt was authorized.

## A. Baselines

- Primary repository HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community repository HEAD: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Community `version.dll` SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- NVIDIA header snapshot: `374959484e79a640feaba44c93ac8cfb0a03f5b5`
- Official runtime used for probe: `C:\Users\mark\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere\_bin`
- Official provider: `nvngx_dlssg.dll`, version `310.9.1.0`, SHA-256
  `FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82`

## B. Actual GPU and identity

The probe selected the actual NVIDIA hardware adapter without matching a
fragile product-name substring:

- DXGI name: `NVIDIA GeForce RTX 3070 Ti`
- Vendor: `0x10DE`
- Device: `0x2482`
- LUID low: `0x0000D82F`
- LUID high: `0x00000000`
- NVAPI full-LUID match: `1`
- NVAPI implementation: `0x4`
- Native architecture: `0x170`

GPU health after the probe remained responsive:

`NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 706 MiB, 39 C, 22%`

## C. Official parameter object

The official-only probe produced:

- D3D12 device: success
- NGX init: `0x00000001`
- parameter allocation via `NVSDK_NGX_D3D12_GetCapabilityParameters`:
  `0x00000001`
- parameter pointer: `0x000001BA5E848360`
- vtable pointer: `0x00007FF91A354970`
- vtable owner: `C:\WINDOWS\System32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\_nvngx.dll`
- unsigned-int Set/Get: pass (`0xA5A55A5A`)
- signed-int Set/Get: pass (`-12345`)
- float Set/Get: pass (`3.25`)
- void-pointer Set/Get: pass
- D3D12 resource pointer round-trip: pass

The public object was not hand-constructed. Its vtable was obtained from the
official NGX-created object.

## D. Cleanup failure boundary

The probe successfully completed `Reset`, parameter destruction, and all typed
round-trip checks. It then logged:

```text
OFFICIAL_NGX_SHUTDOWN_STARTED
```

and remained busy beyond a 20-second bounded watchdog. This occurred with both
`NVSDK_NGX_D3D12_Shutdown1(device)` and the documented all-instance form
`NVSDK_NGX_D3D12_Shutdown1(nullptr)`. The process was terminated by the
watchdog after the timeout. No community DLL had been loaded.

Therefore the official parameter object is demonstrably usable for the public
Set/Get contract, but the current minimal probe does not yet establish a clean
initialization/lifetime contract suitable for passing the community-runtime
gate.

## E. Community runtime

- LoadLibrary: **NO**
- runtime initialization: **NOT RUN**
- CreateFeature: **NOT RUN**
- reset Evaluate: **NOT RUN**
- measured Evaluate: **NOT RUN**
- output resource: **NOT CREATED**

The exact assessed community binary was not executed because the required
official-only probe did not exit cleanly.

## F. Host and build

Created:

- `native\dlssg_sm86_offline\dlssg_sm86_offline.cpp`
- `native\dlssg_sm86_offline\build.ps1`
- `native\dlssg_sm86_offline\README.md`

Build: x64 Release with MSVC `/O2 /EHsc /W4 /Zi /MD`, linked against the
official NVIDIA import library and Windows D3D12/DXGI/system libraries.

Build result: pass after adding `advapi32.lib` and `user32.lib`, which are
required by the official SDK import library.

Selftest result:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
```

Exit code: `0`. Selftest performed no NVIDIA, NGX, D3D12, or community-runtime
loading.

## G. Presentation and output

- swapchain used: `NO`
- Present used: `NO`
- caller-owned output resource: not created in this phase
- readback: not performed

## H. GPU/event safety

No provider or NVIDIA driver file was modified. No community runtime was
loaded. No Create/Evaluate GPU generation was submitted. No TDR or reset was
observed. A narrow System/Application event query covering the preceding 30
minutes returned no matching `nvlddmkm`, `Display`, `WHEA`, Application Error,
or WER events; new `nvlddmkm` Event 153: **NO**.

## I. Next step

`FIX_EXACT_FAILURE_BOUNDARY`

The next offline task is to isolate why the official NGX shutdown path remains
busy after a successful capability-parameter round-trip. Do not load the
community runtime until that probe has a bounded, clean exit.

## J. Git

- No commit.
- No push.
