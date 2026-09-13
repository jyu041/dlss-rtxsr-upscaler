# Phase 4D — mapped-provider readability fix and preflight

## Baselines

- Primary `HEAD`: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- `origin/main`: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Donor `MFGAmpereUnlock-RenoDx`: `c88b208e3f8f12e86a261f06aef1da3a77adef27`
- No reset, commit, or push.

## Root cause

The Phase 4C failure was in `native/dlssg_ampere_reference/ampere_provider.cpp`,
inside `MappedReadable`, before adaptation, NVAPI, D3D12, or NGX. The helper
used an invalid bitwise test against an OR of complete protection constants,
which could reject `PAGE_READONLY`. It also rejected a valid range when the
`VirtualQuery` region was larger than the requested range (`RegionSize > size`),
the inverse of the required containment check.

The provider was loaded with a normal executable-image mapping:

```cpp
LoadLibraryExW(path, nullptr,
               LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR |
               LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)
```

It was not loaded as `DATAFILE` or `IMAGE_RESOURCE`, and the `HMODULE` was not
being converted to a pointer-to-handle. The corrected checks validate committed
regions, reject `PAGE_NOACCESS`/`PAGE_GUARD`, mask protection modifiers, and
verify that the complete requested range fits in the queried region.

The first corrected preflight then exposed two additional local implementation
errors: the temporary image scan used an absolute entry offset as though it were
relative (double-adding the fatbin base), and the transaction restore check used
naive full-value protection equality. Both were fixed narrowly. The provider
adaptation now uses the donor-derived normal module base and exact donor LZ4
block implementation; no whole-image readability assumption remains.

## Read-only provider preflight

Approved provider identity remained unchanged:

- Version: `310.2.1.0`
- SHA-256 before: `15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5`
- SHA-256 after: `15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5`

Observed mapped identity:

```text
PROVIDER_HANDLE=0x00007FF911500000
PROVIDER_BASE=0x00007FF911500000
GETMODULEFILENAME=C:\Windows\System32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\nvngx_dlssg.dll
VQ_BASE_ADDRESS=0x00007FF911500000
VQ_ALLOCATION_BASE=0x00007FF911500000
VQ_ALLOCATION_PROTECT=0x00000080
VQ_REGION_SIZE=4096
VQ_STATE=0x00001000
VQ_PROTECT=0x00000002
VQ_TYPE=0x01000000
DOS_POINTER=0x00007FF911500000
PE_MZ=0x5A4D
PE_SIGNATURE=0x00004550
PE_MAGIC=0x020B
SIZE_OF_IMAGE=9474048
```

The handle, module base, `GetModuleInformation.lpBaseOfDll`, and PE base all
matched. The donor-derived structure scan passed with `257` planned edits and
`79` hidden cubins.

## Apply/rollback preflight

```text
PROVIDER_APPLY_RESULT=1
PROVIDER_VERIFY_RESULT=1
PROVIDER_ROLLBACK_RESULT=1
PROVIDER_POSTROLLBACK_VERIFY=1
PROVIDER_UNLOAD_RESULT=1
```

This was process-local only. The on-disk provider hash remained unchanged.

## Build and selftest

The x64 reference build passed with recovered MSVC and `/W4 /analyze`. The only
reported diagnostics were existing large-stack analyzer warnings in
`standalone_host.cpp` at lines 231 and 636.

Selftest output and result:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
SELFTEST_EXIT_CODE=0
```

Selftest performed no provider load, NVAPI activity, D3D12 creation, NGX call,
or GPU work. The focused readability checks covered committed read-only,
read/write, executable-read, executable-read/write, guard/no-access, reserved,
modifier-bit, and crossing-range cases.

## One live attempt

Exactly one direct attempt was made:

```text
dlssg_ampere_reference.exe --run-2x --provider "C:\Windows\System32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\nvngx_dlssg.dll"
```

It reached:

```text
PROCESS_ENTRY
ARGS_PARSED
PROVIDER_LOADED
PROVIDER_MAPPING_VERIFIED
PROVIDER_MODULE_BASE=0x00007FF911500000
PROVIDER_MODULE_PATH=C:\Windows\System32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\nvngx_dlssg.dll
PROVIDER_EDIT_READBACK=1
PROVIDER_EDIT_PLAN_READY edits=257 hidden_cubins=79
PROVIDER_ADAPTED
Adapter 0: NVIDIA GeForce RTX 3070 Ti, LUID 00000000:0000D82F
GPU_IDENTIFIED
native architecture is not verified as 0x170
NVAPI_HOOK_REMOVAL_RESULT installed=0
PROVIDER_ROLLBACK_RESULT
CLEANUP_COMPLETE
LIVE_EXIT_CODE=20
```

Attempts: `1`. Retries: `0`. The existing live host stopped at its native
architecture verification gate before NVAPI bridge installation, D3D12, NGX,
CreateFeature, Evaluate, fence, or readback. No output artifact exists.

GPU before and after remained responsive: RTX 3070 Ti, driver `610.62`, 8192
MiB total, 35 C, 0% utilization; memory was 592 MiB both samples. The narrow
System/Application event queries found no matching `nvlddmkm`, Display, WHEA,
Application Error, or WER events. New nvlddmkm Event 153: `NO`.

## Result

`REFERENCE_PROVIDER_WORKING`

The Phase 4D objective of fixing the mapped-provider readability failure and
proving safe offline adaptation was achieved. The single live attempt was not
retried; the remaining failure is the pre-existing architecture-verification
gate in the live host.

Next step: `FIX_CURRENT_FAILURE_OFFLINE`.

## Changed reference files

- `ampere_provider.cpp/.h`: corrected mapped-image range validation, donor
  module-base semantics, deterministic plan diagnostics, and apply/rollback path.
- `provider_memory.h`: protection classification and range-containment helpers.
- `donor_lz4.hpp`: attributed donor LZ4 block implementation.
- `provider_transaction.cpp`: modifier-tolerant protection restoration and
  failure diagnostics.
- `standalone_host.cpp`: `--provider-preflight`, mapped-module diagnostics, and
  focused offline readability tests.

No Phase 3 files were deleted or rewritten. No downloaded community binary was
executed; the only executed binaries were locally built project/test outputs.
