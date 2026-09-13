# Phase 4E Architecture Bridge Report

## Result

Primary result: `REFERENCE_NGX_FAILED`.

The isolated architecture bridge passed. The one authorized live attempt reached
provider adaptation, GPU identification, the scoped NVAPI bridge, D3D12 device
creation, and queue creation. It then stopped at the existing DLSS-G
requirements query with `0xBAD00012`, before CreateFeature or Evaluate.

No retry was performed.

## Baselines

- Primary HEAD: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- `origin/main`: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Donor HEAD: `c88b208e3f8f12e86a261f06aef1da3a77adef27`
- No commit or push was performed.

## Phase 4D gate root cause

The old gate was `Bridge::BindAdapter` in `ampere_bridge.cpp`. It required:

```text
original_get_arch_info_(gpu, &architecture_info) == NVAPI_OK
&& architecture_info.architecture == 0x170
```

The earlier implementation supplied a handwritten architecture structure and an
incorrect version field. That made the official NVAPI call fail or produce an
unusable result, and the harness reduced the failure to
`native architecture is not verified as 0x170`.

The fix uses the official local NVAPI declarations, including
`NV_GPU_ARCH_INFO`, `NV_GPU_ARCH_INFO_VER`, and the official handle/status types.
The corrected read-only call now returns architecture `0x170`, implementation
`0x4`, and revision data on the actual RTX 3070 Ti.

## Donor architecture model

- Physical/native Ampere architecture: `0x170`
- Exposed compatibility architecture: `0x190`
- Retargeted PTX target: `sm_86`
- Donor mechanism: scoped hook of the exact `NvAPI_GPU_GetArchInfo` target
  resolved through QueryInterface `0xD8265D24`; the real call runs first and the
  architecture field is changed only for the qualified GPU and scoped call.

The donor uses full DXGI adapter LUID matching and the official
`NV_GPU_ARCH_INFO_VER` structure. The standalone bridge now follows those ABI
and scope rules and does not patch either NVAPI DLL on disk.

## Architecture preflight

The preflight exited `0` with this trace:

```text
NVAPI_SHIM_LOADED
NVAPI_QUERY_INTERFACE_RESOLVED
NVAPI_TARGET_OWNER=C:\WINDOWS\system32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\nvapi64_impl.dll
NVAPI_TARGET_RVA=0x18B7C0
NVAPI_TARGET_PROLOGUE=48895C241855565741564157488DAC2470FFFFFF
GPU_HANDLE_RESOLVED
GPU_VENDOR_ID=0x10DE
GPU_NATIVE_ARCH=0x170
GPU_IMPLEMENTATION=0x4
ARCH_PROFILE=Ampere
ARCH_TARGET_SM=86
ARCH_EXPOSED_VALUE=0x190
ARCH_NATIVE_BEFORE=0x170
ARCH_BRIDGE_INSTALL_RESULT=1
ARCH_BRIDGE_HOOK_CALLS=1
ARCH_BRIDGED=0x190
ARCH_BRIDGE_REMOVE_RESULT=1
ARCH_NATIVE_AFTER=0x170
ARCH_BRIDGE_READY
CLEANUP_COMPLETE
```

The whole architecture structure was compared before and after removal; the
native result and unrelated fields were restored. Page protection and inline
detour cleanup completed successfully.

## Provider architecture gates

The donor scanner was adapted exactly for executable-section comparisons of
`cmp ..., 0x1B0`. On the exact approved `310.2.1.0` provider, the mapped image
contains one executable section, 23 `cmp eax, imm32` candidates and 49
`cmp r32, imm32` candidates with the expected high bytes, but zero `0x1B0`
matches. Therefore no provider architecture-gate edit was invented or applied:

```text
PTX edits: included in 257 total edits
CUBIN hidden count: 79
PROVIDER_ARCH_GATE_COUNT=0
```

The provider’s donor-derived PTX/cubin/requirements edits remained deterministic
and passed apply, verify, rollback, and post-rollback checks. The donor’s gate
scanner would reject a module with zero matches; this exact provider simply has
no matching gate site, so the standalone scanner records zero and proceeds
without a speculative patch.

## Selftest and provider preflight

`--selftest` exited `0`:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
```

Selftest performed no provider load, NVAPI initialization, D3D12 creation, NGX
initialization, or GPU work. Its pure checks include PTX retarget validation and
the readable-page/range classifications, including `PAGE_READONLY`, writable
and executable-readable pages, guard/no-access rejection, reserved-page
rejection, and range crossing rejection.

Provider preflight exited `0`. The mapped module diagnostics showed:

- handle/base: `0x00007FF911500000`
- `GetModuleFileNameW`: the exact approved DriverStore provider path
- allocation base: `0x00007FF911500000`
- state: `MEM_COMMIT` (`0x1000`)
- protection: `PAGE_READONLY` (`0x2`)
- type: `MEM_IMAGE` (`0x1000000`)
- PE: `MZ`, `PE\0\0`, PE32+, `SizeOfImage=9474048`

The preflight reported `edits=257`, `hidden_cubins=79`, apply success,
verification success, rollback success, post-rollback success, and unload
success. The provider SHA-256 before and after was:

`15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5`

## Live attempt

Command, executed once directly:

```text
dlssg_ampere_reference.exe --run-2x --provider "C:\Windows\System32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\nvngx_dlssg.dll"
```

Trace through the last successful stage:

```text
PROCESS_ENTRY
ARGS_PARSED
PROVIDER_LOADED
PROVIDER_MAPPING_VERIFIED
PROVIDER_MODULE_BASE=0x00007FF911500000
PROVIDER_EDIT_READBACK=1
PROVIDER_EDIT_PLAN_READY edits=257 hidden_cubins=79
PROVIDER_ADAPTED
GPU_IDENTIFIED
NVAPI_TARGET_RESOLVED
AMPERE_NATIVE_ARCH=0x170
AMPERE_EXPOSED_ARCH=0x190
AMPERE_BRIDGE_READY
D3D12_CREATED
QUEUE_CREATED
DLSSG_REQUIREMENTS result=0xBAD00012 FeatureSupported=0x0 MinHW=0x0 final=0x0/0x0
NVAPI_HOOK_REMOVAL_RESULT installed=0
PROVIDER_ROLLBACK_RESULT
CLEANUP_COMPLETE
LIVE_EXIT_CODE=20
```

The last successful stage was `QUEUE_CREATED`. No CreateFeature, reset
Evaluate, measured Evaluate, fence, or readback occurred.

## GPU health

Before: RTX 3070 Ti, driver `610.62`, 37 C, P8, 611 MiB / 8192 MiB,
23% utilization.

After: RTX 3070 Ti, driver `610.62`, 39 C, P0, 678 MiB / 8192 MiB,
5% utilization. `nvidia-smi` remained responsive.

No new `nvlddmkm`, Display, WHEA, Application Error, or WER event was found in
the narrow post-run event window. New `nvlddmkm` Event 153: **NO**.

## Files changed in Phase 4E

- `native/dlssg_ampere_reference/ampere_bridge.h`
- `native/dlssg_ampere_reference/ampere_bridge.cpp`
- `native/dlssg_ampere_reference/ampere_provider.cpp`
- `native/dlssg_ampere_reference/standalone_host.cpp`
- this report

The implementation retains the Phase 3 streaming code untouched. Donor-derived
logic is attributed in the source; the mapped-provider LZ4 helper retains its
MIT attribution. The reference executable remains one-process and direct.

## Next step

`FIX_CURRENT_FAILURE_OFFLINE` — investigate the `0xBAD00012` DLSS-G
requirements/capability path before attempting another live run.
