# Isolated Ampere DLSS-G 2x experiment

This is an unsupported, standalone RTX 30 research worker. It is not integrated into WanGP. Phase 3B adds the scoped NVAPI/direct-NGX bridge but deliberately stops before live provider or GPU execution.

The reviewed provider is `nvngx_dlssg.dll` version `310.2.1.0`, SHA-256 `15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5`. The static verdict is `COMPATIBLE_BUT_OUTSIDE_RENO_REVIEWED_POLICY`.

## Phase 3B bridge

`ampere_bridge.cpp` is an independent, process-local call-boundary bridge:

* It loads only `nvapi64.dll` from System32 with `LOAD_LIBRARY_SEARCH_SYSTEM32`.
* It enumerates NVAPI physical GPUs, binds exactly one to the selected DXGI adapter LUID, and verifies the original architecture is Ampere (`0x170`).
* It installs a process-local exact-target inline detour on the resolved `NvAPI_GPU_GetArchInfo` address only after strict provider qualification. QueryInterface is resolved from System32 `nvapi64.dll`, while the returned implementation target is pinned to `nvapi64_impl.dll` version `32.0.16.1062`, SHA-256 `C129247C3F70BFCA49D3F16B28A02D5EE115E541B9F375F154F481A45B35F087`, RVA `0x18B7C0`, and the exact 20-byte position-independent prologue `48895C241855565741564157488DAC2470FFFFFFF`. The copied instructions are `mov [rsp+18],rbx; push rbp; push rsi; push rdi; push r14; push r15; lea rbp,[rsp-90]`; the following `sub rsp,190` is intentionally outside the overwrite. Any mismatch or alternate prologue stops the run. No generic x64 decoder or relocation fallback exists.
* The detour calls the real function first. A thread-local nested scope can expose `0x190` only for Frame Generation requirements, the exact bound NVIDIA adapter, one fully qualified provider, and a successful original call. Shutdown disables qualification before uninstall.
* `BridgeRequirements` calls the real `NVSDK_NGX_D3D12_GetFeatureRequirements`, records raw fields, and only normalizes the Frame Generation architecture-admission pattern to native `0x170` while preserving the function result.
* `BridgeGetCapabilities` calls the real capability function first, then may change `FrameGeneration.Available` from 0 to 1 only for the qualified adapter/provider and accepted driver/init results. It caps `DLSSG.MultiFrameCountMax` at 1. This experiment is strictly 2x: one generated frame and two total temporal outputs.

The policy functions are pure and tested without loading NVAPI, NGX, the provider, D3D12, or CUDA. The real runtime order remains provider preparation, adapter binding, bridge setup, D3D12/NGX initialization, requirements, capabilities, and only then feature creation.

## Provider and safety boundary

The provider session requires canonical absolute path, exact version/hash, strict PE/export/fatbin layout including 97 SM89 PTX and 79 trailing SM89 cubins, duplicate-free edits, transactional writes, protection restoration, readback, and rollback. No provider DLL is redistributed, no modified DLL is emitted, and the source provider is never written. `run_experiment.ps1` is an external Authenticode (`Valid`) and identity pre-run gate with bounded `nvidia-smi`, Windows event collection, and a 60-second outer watchdog; it has not been executed.

This project does not modify drivers, registry values, NVIDIA profiles, HAGS, TDR settings, services, or other processes. It does not inject remote threads or use ReShade/ASI/proxy-DLL deployment. The bridge is an independent implementation informed by public references; no upstream source was copied and no NVIDIA binary, PTX, cubin, or model data is included.

`nvapi_prologue_probe.exe` is a passive inspection utility only: it loads the explicit System32 `nvapi64.dll`, resolves `nvapi_QueryInterface(0xd8265d24)`, validates the returned address against the mapped module, reads bounded bytes, and unloads. It never calls `NvAPI_GPU_GetArchInfo`, initializes NVAPI, loads the provider, installs a hook, or initializes D3D12/NGX. The authorized Phase 3B4 probe stopped because the returned address was not proven inside the mapped System32 image; consequently no real-build RVA or prologue contract is pinned and the live experiment remains unauthorized.

## Build

Use Visual Studio x64 Build Tools and an external official NVIDIA NGX SDK checkout:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -NgxSdk C:\path\to\DLSS
```

The script builds the x64 worker and CPU-only `bridge_policy_tests.exe` with `/W4`. The no-argument worker path only prints usage. Do not run `--probe` or `--serve` during Phase 3B.

At the end of Phase 3B3, NO LIVE RTX 3070 Ti DLSS-G EXPERIMENT HAS YET BEEN RUN: the real NVAPI hook was not installed, the provider was not loaded or modified in memory, D3D12/NGX/CUDA were not initialized, and no GPU work was submitted. This remains an unsupported exact-machine, exact-provider, exact-prologue 2x-only process-local runtime mutation with no modified provider output.
