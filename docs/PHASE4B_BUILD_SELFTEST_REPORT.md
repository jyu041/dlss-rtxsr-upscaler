# Phase 4B — Windows toolchain, donor build, and reference selftest

Date: 2026-09-13. No commit and no push.

## A. Toolchain

Repository identity gates passed:

- Primary `HEAD`: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Primary `origin/main`: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- `git diff --check`: passed
- Donor `HEAD`: `c88b208e3f8f12e86a261f06aef1da3a77adef27`
- Donor working tree: clean

Visual Studio was present but not on the inherited PATH; no new compiler was installed.

| Component | Result |
|---|---|
| Installation | `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools` |
| Product | Visual Studio Build Tools 2022, `17.14.40`, installation `17.14.37628.2` |
| MSVC | `14.44.35207` tool directory; compiler/linker report `19.44.35228` / `14.44.35228` |
| `cl.exe` | `...\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe` |
| `link.exe` | matching Hostx64/x64 path |
| MSBuild | `...\Msbuild\Current\Bin\amd64\MSBuild.exe`, `17.14.51.32402` |
| Windows SDK | `10.0.26100.0` |
| CMake | bundled VS CMake, `3.31.6-msvc6` |

`vcvars64.bat` activation succeeded. A harmless x64 CPU smoke program compiled, linked, and ran with exit code 0.

RenoDX’s own setup script installed the documented Slang `2026.14.1` and glslang `16.5.0` tools into the separate research tree. The installed Windows SDK DXC is `1.8.2502.11`; RenoDX emitted a warning that its recommended minimum is `1.9.2602`, but configuration continued successfully.

## B. Donor build

RenoDX was cloned recursively at commit `cd32113a98608e63027d40910cfe296a14dfe228`. NVIDIA NVAPI was cloned at the donor-requested commit `87dca625e83fd89a983e19b904e5f3a580da90d2`.

The donor source was copied into `renodx/src/addons/mfgunlock` as instructed. Configure command:

```text
cmake --preset vs-x64
```

with `vcvars64.bat`, `CL=/I"...\renodx\external\NVAPI"`, and the RenoDX `bin` directory on PATH.

Build command:

```text
cmake --build --preset vs-x64-release --target mfgunlock
```

Result: `DONOR_SOURCE_BUILD_PASS`.

Artifact:

`C:\Users\mark\Desktop\dlss-community-research\renodx\build.vs\Release\renodx-mfgunlock.addon64`

- Size: 441,856 bytes
- SHA-256: `0FE9798C0F48AD7ADBC0E22546743221EB6397BDEAE804E438297EA133611F81`
- No donor addon was installed into a game or executed.

## C. Reference harness

Files currently present in `native/dlssg_ampere_reference/`:

- `main.cpp`
- `reference_core.hpp`
- `CMakeLists.txt`
- `build.ps1`
- `README.md`

The executable is a direct one-process CLI with `--selftest` and `--run-2x <provider>` argument forms. It has no stdin streaming, JSON loop, parent/child protocol, ReShade, RenoDX runtime dependency, ASI loader, or downloaded binary dependency.

The donor-derived pure core currently covers:

- Ampere family `0x170`, exposed Ada `0x190`, target SM86;
- implementation-nonzero Ampere admission;
- exact provider version/hash contract;
- generated-frame mapping for 2X/3X/4X;
- synthetic 256×256 input contract;
- fail-closed PTX `sm_89` recognition and `sm_89` → `sm_86` transformation;
- malformed/unrelated PTX rejection;
- reviewed mixed-fatbin/cubin-hide decision checks.

Attribution is retained in `reference_core.hpp` and `README.md` for MIT donor commit `c88b208e3f8f12e86a261f06aef1da3a77adef27`.

Build command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\native\dlssg_ampere_reference\build.ps1
```

Compiler settings include `/O2 /EHsc /W4 /MD`. Result: `REFERENCE_HARNESS_BUILD_PASS`.

Artifact SHA-256: `353C39CC946AFFFE20AE6F39D1160B193D824D82399EAD1D40A789AE077E9FA3`.

Important limitation: the live path remains explicitly fail-closed with `LIVE_REFERENCE_NOT_BUILT`. The minimal D3D12/NGX/provider publication host requested for a real 2X call is not yet implemented in this harness.

## D. Selftest

Command:

```text
native\dlssg_ampere_reference\build\dlssg_ampere_reference.exe --selftest
```

Exact stderr trace:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
```

Exit code: `0`.

Selftest exercised only process startup, argument parsing, pure configuration, PTX synthetic transformation checks, fatbin decision checks, and logging. NVIDIA/GPU activity: **NONE**.

## E. Offline transformation tests

Passed inside selftest:

- `sm_89` target recognized;
- exact `sm_89` → `sm_86` transformation;
- PTX 7.8 rejected;
- duplicate/missing target rejected;
- mixed-fatbin/cubin-hide decision accepted only for reviewed structure;
- malformed competing-cubin structure rejected;
- synthetic motion/depth/format dimensions accepted only for the requested 256×256 2X case.

No real provider file was opened, changed, or emitted.

## F. Live attempt

Executed: **NO**.

Attempt count: `0`.

The non-live build/selftest gates passed, but the executable’s live path is an intentional fail-closed placeholder and does not create D3D12, load NVAPI/NGX, adapt the provider, or call CreateFeature/Evaluate. Running it would not be a valid Phase 4B reference attempt, so the one-attempt allowance was preserved.

## G. MFG

No live provider adaptation, NGX initialization, capability query, CreateFeature, Evaluate, fence, readback, or output hash occurred.

## H. GPU health

- Before: no GPU activity from this task.
- After: no GPU activity from this task.
- Windows error events: not queried because no live attempt occurred.
- `nvlddmkm` Event 153: not applicable.

## I. Primary classification

`REASSESS_DONOR_IMPLEMENTATION`

The Windows build/toolchain and donor source gates are recovered and passing. The remaining work is to port the donor’s mapped-provider publication and architecture/capability bridge into the standalone D3D12 host; the current executable must not be treated as live-capable.

## J. Next step

`REASSESS_DONOR_IMPLEMENTATION` — implement the donor-derived provider publication and minimal D3D12/NGX host before authorizing the one live 2X attempt. No next step was executed in this task.

## K. Git

- No commit.
- No push.
