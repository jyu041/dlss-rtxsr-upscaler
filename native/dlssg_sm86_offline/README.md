# DLSS-G SM86 Offline Host

This source-only x64 D3D12 harness uses an official NVIDIA NGX parameter object
with the public NGX ABI exported by the community `dlssg_for_sm86` runtime. It
supports a GPU-free `--selftest`, focused probes, a resource-pipeline test, the
proven single-shot `--run-2x` path, and a persistent binary-protocol `--serve`
mode. No swapchain or Present is used.

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
.\bin\dlssg_sm86_offline.exe --serve --community-runtime <absolute-community-version.dll> --official-runtime-dir <official-runtime-directory>
```

## Persistent worker

`--serve` keeps one D3D12 device, one direct queue, one official NGX parameter
object, one loaded community runtime, and one DLSS-G feature alive for many
frames. Standard input and output carry the versioned binary protocol in
`worker_protocol.h`; all native diagnostics go to standard error.

Protocol version 1 supports `HELLO`, `CREATE`, `PROCESS`, `RESET_HISTORY`, and
`CLOSE`. The first `PROCESS` after `CREATE` or `RESET_HISTORY` is forced to be a
reset/bootstrap frame and intentionally returns no generated frame. Every later
successful `PROCESS` returns one tightly packed 256x256 RGBA8 midpoint frame.
Frame IDs must increase monotonically for the lifetime of the worker, including
across history resets.

This first implementation is deliberately fixed to 256x256, 2X, and internally
maintained constant R32_FLOAT depth 0.5. The caller supplies:

- current color as tightly packed RGBA8 (`width * height * 4` bytes);
- motion as tightly packed R16G16_FLOAT (`width * height * 4` bytes), with two
  little-endian IEEE-754 half values per pixel;
- current-to-previous motion, with the established normalized scale of
  `(1 / width, 1 / height)` used by the native Evaluate contract.

Constant depth is useful for the synthetic proof but is not a production depth
model for arbitrary footage. Caller-supplied depth and resizing are reserved in
the protocol but intentionally rejected by version 1.

The Python API is `src.backends.dlssg_worker.DlssgWorker`:

```python
from src.backends.dlssg_worker import DlssgWorker

with DlssgWorker(worker_exe, community_version_dll, official_runtime_dir) as worker:
    worker.create(256, 256)
    worker.process(0, rgba0, zero_motion, reset=True)  # bootstrap; no output
    midpoint = worker.process(1, rgba1, motion1).output
    worker.reset_history()
```

The client validates path identity, protocol layout/version, payload sizes,
finite half-float motion values, short reads, native statuses, and worker exits.
It drains stderr independently so diagnostics cannot deadlock the protocol.
`CLOSE` is bounded and falls back to process termination rather than invoking
the known-hanging NGX shutdown entry point.

The official NGX shutdown path is deliberately not called because it is known
to hang in this experimental stack. See `docs/PHASE5R_OFFLINE_2X_MILESTONE.md`
for the exact successful contract and output evidence.
