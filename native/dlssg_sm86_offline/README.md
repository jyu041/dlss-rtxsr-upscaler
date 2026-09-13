# DLSS-G SM86 Offline Host

This source-only x64 D3D12 harness uses an official NVIDIA NGX parameter object
with the public NGX ABI exported by the community `dlssg_for_sm86` runtime. It
supports a GPU-free `--selftest`, focused probes, a resource-pipeline test, and
the proven single-shot `--run-2x` path. No swapchain or Present is used.

## External dependencies

The build requires a locally staged official NVIDIA NGX SDK and public NVAPI
headers. Their paths can be passed to `build.ps1` with `-NgxSdk` and `-NvApi`.
These SDK payloads are not part of this repository.

The community `version.dll` is an external, user-supplied runtime dependency.
It is not downloaded, embedded, committed, or redistributed by this project.
The runtime used for the Phase 5R milestone had SHA-256:

```text
C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2
```

That identity is provenance, not a safety guarantee; its Authenticode signer is
self-signed. Users must make their own trust decision and pass an absolute path
to the runtime.

## Commands

```powershell
.\build.ps1
.\bin\dlssg_sm86_offline.exe --selftest
.\bin\dlssg_sm86_offline.exe --resource-pipeline-test
.\bin\dlssg_sm86_offline.exe --run-2x <absolute-community-version.dll> <official-runtime-directory>
```

The official NGX shutdown path is deliberately not called because it is known
to hang in this experimental stack. See `docs/PHASE5R_OFFLINE_2X_MILESTONE.md`
for the exact successful contract and output evidence.
