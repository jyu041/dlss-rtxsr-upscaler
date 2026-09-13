# Phase 4C — Standalone 2X Ampere DLSS-G path

Date: 2026-09-13. No commit and no push.

## A. Implementation

Baselines passed:

- Primary `HEAD` and `origin/main`: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Donor `HEAD`: `c88b208e3f8f12e86a261f06aef1da3a77adef27`
- `git diff --check`: passed before implementation

New/updated reference files:

- `native/dlssg_ampere_reference/standalone_host.cpp`
- `native/dlssg_ampere_reference/ampere_provider.cpp/.h`
- `native/dlssg_ampere_reference/ampere_bridge.cpp/.h`
- `native/dlssg_ampere_reference/provider_transaction.cpp/.h`
- `native/dlssg_ampere_reference/reference_core.hpp`
- `native/dlssg_ampere_reference/build.ps1`
- `native/dlssg_ampere_reference/CMakeLists.txt`

The host is now one process and one command. It has no stdin protocol, parent/child pipes, JSON loop, or serve mode. It creates a single DXGI/D3D12 adapter/device/direct queue/allocator/list/fence, prepares RGBA8, R16G16_FLOAT motion, R32_FLOAT depth, output/readback resources, initializes NGX, creates DLSS-G, performs one reset Evaluate and one measured Evaluate, waits on a 15-second fence, and reads one generated frame.

The useful D3D12/NGX host code was adapted from the existing Phase 3 host without carrying over its process protocol. The provider/bridge implementation in this attempt is the existing exact-provider transaction/bridge source copied into the new standalone path; `reference_core.hpp` adds donor-attributed pure checks for the donor’s Ampere/SM86/PTX/cubin decisions. This is important: the live provider publication is not yet a complete port of the donor’s current mapped-image publication mechanism.

Attribution remains in `reference_core.hpp` and `README.md` for MIT donor commit `c88b208e3f8f12e86a261f06aef1da3a77adef27`. NVIDIA NGX headers/libs remain external and are not redistributed.

## B. Provider publication and identity

The attempted path loads the exact canonical provider with `LoadLibraryExW`, validates version/hash/path before mutation, adapts only mapped process memory, and rolls back before process exit. It does not modify the provider file on disk.

The required provider preflight passed:

- Path: `C:\Windows\System32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\nvngx_dlssg.dll`
- Version: `310.2.1.0`
- SHA-256: `15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5`
- Authenticode: `Valid`

The process-local mapping failed its first PE read check: `mapped provider DOS header is not readable`. Therefore no module base/path diagnostic proving NGX’s active provider instance was reached, and no edits were applied.

## C. Build

Compiler: MSVC 19.44.35228 x64.

Build command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\native\dlssg_ampere_reference\build.ps1
```

Settings: `/O2 /EHsc /W4 /analyze /MD`, linked against the local RenoDX DLSS SDK, D3D12, DXGI, version, bcrypt, advapi32, user32, and psapi libraries.

Result: `REFERENCE_BUILD_PASS`.

The only emitted analyzer warning was C6262 for a large stack frame in the existing host setup (`65612` bytes); compilation and linking completed successfully.

## D. Selftest

Command:

```text
native\dlssg_ampere_reference\build\dlssg_ampere_reference.exe --selftest
```

Trace and exit:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
EXIT_CODE=0
```

Selftest remained GPU/NVIDIA-free: it did not load NVAPI, load the provider, install a bridge, create D3D12, initialize NGX, or submit GPU work.

## E. Offline tests

Passed in the pure selftest path:

- expected `.target sm_89` recognized;
- `.target sm_89` converted to `.target sm_86`;
- PTX 7.8 rejected;
- unrelated SM75 target rejected;
- duplicate/missing target rejected;
- mixed-fatbin/cubin-hide decision checks passed;
- malformed layout decision rejected;
- exact 2X generated-frame mapping remained `1`.

No real provider file was modified.

## F. Live attempt

Executed: **YES**.

- Exact command: `dlssg_ampere_reference.exe --run-2x --provider "C:\Windows\System32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\nvngx_dlssg.dll"`
- Attempts: `1`
- Retries: `0`
- Resolution/semantics configured: 256×256, one generated frame, 2X

Exact flushed trace:

```text
PROCESS_ENTRY
ARGS_PARSED
PROVIDER_ADAPTATION_FAILED: mapped provider DOS header is not readable
NVAPI_HOOK_REMOVAL_RESULT installed=0
PROVIDER_ROLLBACK_RESULT
CLEANUP_COMPLETE
EXIT_CODE=20
```

Last successful stage: argument parsing. No GPU stage was reached.

## G. Ampere bridge

Not reached in the live attempt. The planned scoped bridge would have used native architecture `0x170` and exposed architecture `0x190`, but the provider adaptation gate failed before bridge setup.

## H. Provider

- Identity: passed before execution.
- File loaded: attempted by the process, but mapped-image validation failed immediately.
- Adapted: **NO**.
- Edits: `0` applied; rollback completed.
- Failure: mapped provider DOS header was not readable from the loaded module mapping.

## I. NGX

Not reached:

- NGX init: not attempted
- Capability query: not attempted
- `FG_AVAILABLE`: not queried
- `MultiFrameCountMax`: not queried
- CreateFeature: not attempted
- Reset Evaluate: not attempted
- Measured Evaluate: not attempted

## J. Output

No generated output was produced. No readback or output hash exists.

## K. GPU health

Before:

```text
NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 602 MiB, 37 C, 22 %
```

After:

```text
NVIDIA GeForce RTX 3070 Ti, 610.62, 8192 MiB, 604 MiB, 37 C, 20 %
```

No relevant `nvlddmkm`, Display, WHEA, Application Error, or WER events were returned in the narrow event windows. New `nvlddmkm` Event 153: **NO**.

## L. Primary result

`REFERENCE_PROVIDER_FAILED`

## M. Next step

`FIX_CURRENT_FAILURE_OFFLINE` — fix the standalone provider mapped-image validation/publication path and prove the loaded module identity before another live attempt. No retry was made in this task.

## N. Git

- No commit.
- No push.
