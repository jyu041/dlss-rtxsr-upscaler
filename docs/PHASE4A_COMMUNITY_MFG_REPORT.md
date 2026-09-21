# Phase 4A — Community MFG Reference Harness

Date: 2026-09-13. No commit and no push were performed.

## A. Community repositories

| Repository | branch / exact HEAD | license | source/build status |
|---|---|---|---|
| [nefh/MFGAmpereUnlock-RenoDx](https://github.com/nefh/MFGAmpereUnlock-RenoDx) | `main` / `c88b208e3f8f12e86a261f06aef1da3a77adef27` | MIT | Relevant Ampere source is visible under `src/addons/mfgunlock`; the donor validation suite is source-buildable with CMake. The full addon depends on RenoDX/ReShade/NVAPI trees. No NVIDIA runtime is included. |
| [mcsoderh/RTX30MFG-Unlock](https://github.com/mcsoderh/RTX30MFG-Unlock) | `main` / `21a2b9931f0c13f46a4b3b8a5856620d9698f88e` | MIT; vendored MinHook retains its own license | Relevant Ampere source is visible under `source/native`; CMake requires Streamline, NGX, and optional ReShade/ImGui trees. The checked-in `bin` contains a prebuilt mod, which was not executed. |
| [sdli1995/dlssg_for_sm86](https://github.com/sdli1995/dlssg_for_sm86) | `main` / `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40` | Repository notices describe GPLv3 source ancestry and separate NVIDIA/proprietary runtime material; no standalone root license file was present | Host/runtime implementation is not source-visible. The root `version.dll` is a 15,667,520-byte prebuilt binary. Static hash: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`; signature is self-signed and not trusted by the local trust provider. Classified `FUNCTIONAL_REFERENCE_ONLY_BINARY_RUNTIME`. |

The three trees were cloned into `C:\Users\<user>\Desktop\dlss-community-research`. No downloaded DLL, EXE, ASI, or proxy was executed.

## B. Donor comparison

### MFGAmpereUnlock-RenoDx

The actual implementation detects NVIDIA architecture through `NvAPI_GPU_GetArchInfo`; Ampere is architecture `0x170`, with nonzero implementation required to exclude GA100/SM80 from the reviewed SM86 route. Its Ampere profile exposes `0x190` (Ada) to the provider-facing capability path and retargets CUDA code to SM86. The architecture hook is scoped to the bound GPU and NGX capability/requirements calls rather than globally changing every query.

Provider discovery watches `nvngx_dlssg.dll`, NGX-looking modules, and late loads. A mapped-image identity (timestamp and image size), readable PE bounds, export/layout checks, and provider state prevent arbitrary modules from being edited. The current source does not advertise a special 310.2.1 profile; its temporal profiles explicitly discuss 310.9 layouts. Therefore compatibility with the requested 310.2.1 provider remains an unresolved gate, not an assumption.

The PTX path accepts one verified `.target sm_89`, one PTX version in the reviewed 8.x range through 8.7, one address-space directive, and reviewed fatbin ordering/flags. It LZ4-decompresses the PTX, confirms the target digit is an independent LZ4 literal, changes only `sm_89` to `sm_86` (or `sm_75`), rewrites the entry architecture field, and hides a trailing matching cubin in mixed layouts. The temporal correction separately rebuilds a known D157 PTX, replaces the midpoint constants, emits an uncompressed aligned entry, truncates away the preferred cubin, and redirects descriptor slots in mapped memory. Unknown layouts are rejected.

Capabilities are changed only after provider/temporal readiness: `FrameGeneration.Available` may change from zero to one only when the existing driver/init evidence is acceptable, and `DLSSG.MultiFrameCountMax` is raised through the configured limit. Streamline options express generated frames, so 2X/3X/4X map to 1/2/3 generated frames. Cleanup unregisters hooks, restores midpoint/provider/ceiling/pacing edits, and releases allocations.

### RTX30MFG-Unlock

This implementation uses a stricter adapter admission path: DXGI adapter LUID is matched to exactly one CUDA device, NVIDIA is verified, and compute capability must be exactly 8.6 for Ampere. It has a second source-visible provider bundle implementation that discovers gate sites from the image, changes the architecture immediate from Ada to Ampere, scans all fatbin containers, changes the independent `.target sm_89` LZ4 literal to `sm_86`, rewrites the entry architecture field, and shortens the container so trailing SM89 cubins are not selectable. It also preserves a published cloned descriptor/fatbin and rolls back transactionally.

Its provider policy explicitly covers a table of provider versions, with current tests centered on 310.9.1; the source test names reject unknown 310.9.2. No source evidence found a reviewed 310.2.1 implementation. Midpoint correction is a separate cloned-fatbin publication path and includes adapter/provider identity, source/output SHA-256, descriptor validation, and restart-required behavior if the adapter changes. It supports 2X through 5X admission in policy (one through four generated frames), while actual Streamline/game limits can still reduce the published maximum.

### Side-by-side mechanism matrix

| Mechanism | Phase 3 ours | RenoDx donor | RTX30 donor | Classification |
|---|---|---|---|---|
| Native Ampere value `0x170` | Yes, exact-provider bridge | Yes | Yes, plus CUDA CC 8.6 | SAME; community adds an independent CUDA/LUID admission check |
| Exposed value `0x190` | Scoped bridge policy | Scoped to FG/provider capability path | Provider gate rewrite plus adapter admission | DIFFERENT |
| Provider version/hash gate | Exact 310.2.1/hash | Structural mapped-image validation; no 310.2.1 evidence | Explicit version/profile table; no 310.2.1 evidence | OURS MORE COMPLEX for identity, community broader by layout/profile |
| PTX `sm_89` → `sm_86` | Transactional provider logic exists | Direct donor retargeter with literal validation | Direct donor bundle planner with all-container scan | SAME core mechanism |
| LZ4 literal provenance check | Yes | Yes | Yes | SAME |
| Hidden/trailing cubins | Strict reviewed layout | Mixed-entry cubin hidden | Payload shortening hides cubins | SAME, donor wording/coverage clearer |
| Fatbin handling | Exact reviewed 310.2.1 assumptions | Single/mixed reviewed orders | All-container plan with explicit budget | DIFFERENT; community is less tied to one provider identity |
| Midpoint correction | Not live-completed in Phase 3 | D157 temporal PTX rewrite | Cloned descriptor/output-hash publication | MISSING_IN_OURS at runtime |
| Capability keys | `FrameGeneration.Available`, max=1 | Available + max, preserves driver/init evidence | Streamline/NGX dynamic publication | SAME core; donor supports broader counts |
| Multiplier semantics | 2X only | configurable 2–6x | policy 2–5x | OURS MORE RESTRICTIVE |
| Adapter binding | NVAPI physical GPU ↔ DXGI LUID | bound GPU scope | DXGI ↔ CUDA LUID uniqueness | COMMUNITY_ONLY addition in RTX30 |
| Provider discovery | direct explicit provider path | late-load and renamed-module inventory | loader/entry detours and policy routing | OURS MORE COMPLEX in preload safety, donor broader discovery |
| Cleanup | rollback/lifetime state machine | restore mapped patches and allocations | pinned provider/clone rollback | SAME; RTX30 has more publication lifetime machinery |
| Streaming worker / pipes | Yes | No | No | NOT_RELEVANT_TO_STANDALONE; removed from Phase 4A |

Top five differences most likely to determine MFG success:

1. The community code retargets every eligible fatbin and deliberately makes SM89 cubins unselectable, while Phase 3 is tied to a narrower exact-provider transaction.
2. Both donors validate the actual PTX target as an independent compressed literal before editing; the runtime JIT route is therefore explicit rather than inferred.
3. Both donors have a separate temporal midpoint correction, including the preferred-cubin problem; Phase 3 did not reach a live temporal publication.
4. RTX30MFG-Unlock proves the active DXGI adapter against exactly one CUDA device/LUID and CC 8.6, adding a hardware identity gate absent from the simpler path.
5. Community capability publication is conditioned on provider/temporal readiness and supports generated-frame counts beyond Phase 3's hard 2X ceiling.

## C. Chosen donor

Chosen donor: `nefh/MFGAmpereUnlock-RenoDx`, commit `c88b208e3f8f12e86a261f06aef1da3a77adef27`.

It has the smallest separable pure core, a source-visible validation CMake project, clear MIT licensing, explicit PTX/fatbin validation, and no need to execute a bundled binary. Its current source still needs a new 310.2.1 compatibility proof before live use.

## D. Donor build

Intended command:

```powershell
cmake -S C:\Users\<user>\Desktop\dlss-community-research\MFGAmpereUnlock-RenoDx\contrib\validation -B temp\mfgampere-validation -G "Visual Studio 17 2022" -A x64
cmake --build temp\mfgampere-validation --config Release
ctest --test-dir temp\mfgampere-validation -C Release --output-on-failure
```

Actual result: `cmake` was not present on PATH, and no `cl`, `msbuild`, `clang++`, `clang-cl`, or MinGW compiler was found. Therefore no donor executable or DLL was built, no output artifact exists, and the build gate is `BUILD_BLOCKED`. This also means no community binary was executed.

## E. New harness

Added under `native/dlssg_ampere_reference/`:

- `main.cpp` — one-process command-line entry, flushed stage logging, `--selftest`, and fail-closed live placeholder.
- `reference_core.hpp` — small donor-attributed pure architecture/provider/multiplier validation core.
- `CMakeLists.txt` and `build.ps1` — x64 MSVC build entry points.
- `README.md` — scope, attribution, and safety boundary.

The harness has no stdin protocol, serve mode, pipes, JSON loop, multiple worker messages, global hooks, or provider-on-disk mutation. Runtime artifacts are reserved under its gitignored `runtime/` directory. The existing `native/dlssg_ampere_experiment/` tree was not modified.

The current live function is intentionally fail-closed until a compiler and NVIDIA NGX SDK are available to wire the minimal D3D12 device/queue/textures/upload/MV/depth/NGX/Create/Evaluate/fence/readback path. It is not represented as a successful native runtime.

## F. Selftest

Not run: the executable could not be built because the local Windows C++ toolchain is unavailable. Consequently the required exit code 0 and exact flushed trace are unverified. The source emits the required sequence on the successful path:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
```

No NVIDIA DLL, D3D12, NGX, provider mutation, or GPU activity occurred.

## G. Live reference attempt

Executed: **NO**.

Reason: donor build blocked, new harness build blocked, and selftest therefore could not pass. The one-attempt authorization gate was not reached. There was no provider load, architecture bridge, NGX initialization, CreateFeature, Evaluate, readback, or GPU health event.

The requested provider contract was recorded but not opened or modified: exact path under the specified DriverStore directory, version `310.2.1.0`, SHA-256 `15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5`, and required Authenticode `Valid`.

## H. Result

`BUILD_BLOCKED`

## I. DLSS5 next

Next source repository to study: [wilsjo2/OptiScaler-DLSSNR-PreSR-Multipass](https://github.com/wilsjo2/OptiScaler-DLSSNR-PreSR-Multipass).

Concrete later inventory:

- Pre-SR Neural Rendering integration and route selection;
- multipass NR scheduling and intermediate-resource contracts;
- per-pass controls and configuration boundaries;
- motion-vector and resource-format/ownership fixes;
- frame/resource lifetime, reset, and reuse fixes.

This is inventory only; MFG remains the priority.

## J. Git

- No commit.
- No push.
