# Persistent Offline DLSS-G 2X Worker

## A. Checkpoint

The successful one-shot offline proof was preserved before the worker refactor:

- commit: `9ef7f8c81cec5e1780f7fb8605dd5ccaeefb14bc`
- message: `feat: prove offline DLSSG 2x on Ampere`
- contents: Phase 4/5 source, tests, reports, and the reproducible
  `native/dlssg_sm86_offline` host
- hygiene: no DLL, EXE, PDB, ILK, SDK payload, community runtime, generated raw
  output, or runtime log was tracked
- validation before commit: x64 Release build passed, native selftest passed,
  relevant Python tests passed, and `git diff --check` passed

The community runtime and generated evidence remain ignored external/runtime
artifacts. A first push attempt was interrupted after the remote produced no
response; final push state is recorded in the task handoff rather than guessed.

## B. Architecture

The worker is a direct extension of the proven public-NGX-ABI path in
`native/dlssg_sm86_offline/community_run2x.cpp`. It does not use Streamline,
a swapchain, or Present.

`PersistentWorker` owns for the process lifetime:

- the selected NVIDIA DXGI adapter and its full-LUID NVAPI verification;
- one D3D12 device, direct queue, command allocator/list, fence, and event;
- one official NVIDIA `NVSDK_NGX_Parameter` object;
- one absolute-path-loaded community runtime and its Init/Create/Evaluate
  exports;
- one FrameGeneration feature handle;
- reusable color, R16G16_FLOAT motion, constant-depth, interpolated-output, and
  four-byte disable-output resources;
- reusable upload and readback buffers plus explicit resource-state tracking;
- monotonic frame/history state and lifecycle counters.

The synchronous command lifecycle is Begin/record/Close/Execute/Signal/Wait/
Reset. An allocator is never reset while GPU work is outstanding, and the
command list is never reset while open. Inputs are returned to
`NON_PIXEL_SHADER_RESOURCE`; generated output and disable output are maintained
as UAV resources except for explicit ordered copy transitions.

Init and feature creation occur once. Fixed-size resources are reused on every
PROCESS request. Protocol v2 additionally supports internal NVIDIA Optical Flow
and recreates only size-dependent NVOF/DLSS-G state after a changed CREATE.

## C. Protocol

`native/dlssg_sm86_offline/worker_protocol.h` defines a packed little-endian
protocol with magic `0x47534C44`, protocol version 2, worker version 2, and
compile-time structure-size assertions.

| Command | Request | Response |
|---|---|---|
| HELLO | header only | worker/protocol versions and capability bits |
| CREATE | width, height, DXGI format, generated count, depth mode | status, versions, maximum generated frames, active depth mode |
| PROCESS | frame ID, flags, byte counts, RGBA8 bytes, R16G16_FLOAT bytes | status, output metadata, timings, packed RGBA8 bytes |
| RESET_HISTORY | header only | status |
| CLOSE | header only | status, flushed before deliberate process exit |

Header sizes are 16-byte request and 20-byte response. Request IDs correlate
responses. Payloads are bounded to 64 MiB. Status 0 is success; status 1 means a
successful reset/bootstrap Evaluate with intentionally no output. Negative
statuses distinguish malformed protocol, invalid state/dimensions/format/frame
ID, native failure, disabled interpolation, and invalid output.

Stdout is protocol-only. Immediate native diagnostics and lifecycle counters go
to stderr.

## D. History model

- CREATE marks history invalid.
- The first PROCESS is forced to reset even if the caller omits the flag. It
  executes Evaluate, establishes history, and returns no generated output.
- Later PROCESS messages use reset=false and return one midpoint when
  interpolation is enabled.
- RESET_HISTORY marks history invalid without recreating the feature.
- The next PROCESS is again forced to reset and returns no output.
- BackbufferFrameID must increase for every PROCESS across the entire worker
  lifetime. IDs deliberately continue across RESET_HISTORY.
- A duplicate or decreasing frame ID fails closed.

This prevents interpolation across unrelated sequences while preserving one
persistent feature instance.

## E. External runtime

The community `version.dll` is user supplied by absolute path. It is not
downloaded, embedded, committed, or redistributed. The proven runtime identity
is SHA-256
`C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`.
The Python client warns on a different hash by default and can enforce the known
hash, but the hash is provenance only and does not establish safety.

The official NGX runtime directory is also supplied externally. The repository
contains no NVIDIA SDK payload or matched runtime DLL.

## F. Python client

`src/backends/dlssg_worker.py` exposes `DlssgWorker.start`, `create`, `process`,
`reset_history`, and `close`, plus context-manager use. It launches the native
worker directly with binary pipes, checks magic/version/request correlation,
performs exact partial reads/writes, validates paths and input byte counts,
rejects non-finite half-float motion, surfaces native status codes, and detects
early process exit.

Stderr is drained on a separate daemon thread and can be forwarded through a
callback. CLOSE receives its protocol acknowledgement before the native process
uses the documented no-NGX-shutdown exit path. The client waits at most five
seconds, then terminates/kills if necessary, so application shutdown cannot
wait forever on the known NGX shutdown defect.

## G. Tests

- x64 MSVC Release `/W4` build: PASS
- native `--selftest`: PASS, including protocol layout and history-state checks
- focused DLSS-G Python suite: 19 passed in 0.11 s
- exact/partial read and write handling: PASS
- invalid magic/version: PASS
- incorrect color and motion byte counts: PASS
- non-finite half-float motion rejection: PASS
- short-read/process failure handling: PASS
- native status propagation: PASS
- persistent synthetic GPU sequence: PASS

The persistent test manifest is written under ignored
`native/dlssg_sm86_offline/runtime/output/`.

For transparency, the full repository suite in the available Python environment
reported 57 passed, 2 skipped, and 2 unrelated WebUI failures. The environment
has Gradio 5.29.0 while `requirements.txt` pins 6.16.0; both failures concern the
location of the `css_paths` launch argument. No DLSS-G test failed, and this task
did not rewrite unrelated UI code to accommodate the mismatched environment.

## H. Live persistence result

One `--serve` process was driven by `tools/dlssg_persistent_test.py`:

- processes: 1
- official/community initialization count: 1
- feature instances/CreateFeature count: 1
- input frames: 21
- Evaluate calls: 21
- generated outputs: 19
- first sequence: frame 0 reset plus frames 1-15 normal, producing 15 outputs
- RESET_HISTORY: honored in the same process
- second sequence: frame 16 forced reset plus frames 17-20 normal, producing 4 outputs
- output bytes: 262,144 each, tightly packed 256x256 RGBA8
- disable-interpolation: 0 for every successful output
- unique generated SHA-256 values: 19 of 19
- all outputs: nonzero, nonconstant, different from the current input, different
  from the known sentinel, and not a stale duplicate of the preceding output
- process exit: normal after acknowledged CLOSE
- NGX Shutdown/Shutdown1: deliberately not called

The reset sequence changed direction and remained valid after history was
invalidated, without process or feature recreation.

## I. Performance

For the 19 generated frames at 256x256:

| Timing | Minimum | Mean | Maximum |
|---|---:|---:|---:|
| upload | 1.153 ms | 1.735 ms | 3.757 ms |
| Evaluate CPU call | 0.302 ms | 0.373 ms | 0.506 ms |
| GPU fence wait | 2.926 ms | 4.438 ms | 8.221 ms |
| readback | 0.268 ms | 0.676 ms | 1.974 ms |
| total PROCESS | 4.919 ms | 7.412 ms | 10.576 ms |

These are synchronous correctness-first measurements. No multi-inflight work or
throughput optimization was attempted.

## J. GPU health

Before the live persistence test:

- NVIDIA GeForce RTX 3070 Ti, driver 610.62
- VRAM 703/8192 MiB
- 40 C
- 22% utilization

After the test:

- NVIDIA GeForce RTX 3070 Ti, driver 610.62
- VRAM 691/8192 MiB
- 41 C
- 22% utilization

The bounded System/Application event query returned no matching nvlddmkm,
Display, WHEA, Application Error, or WER events. New nvlddmkm Event 153: NO.

## K. Application integration status

The clean integration point is the new `src.backends.dlssg_worker.DlssgWorker`
API. It is an independent interpolation stage and does not replace RTX VSR,
DLSS SR, or DLSS 5. Existing video pipelines can retain a worker for one render
job and emit each real frame plus the returned midpoint before encoding at 2X
the source frame rate.

The backend is intentionally not wired into the UI or video encoder yet. The
application currently has no production motion-vector source for this path.
Callers must supply full-resolution R16G16_FLOAT current-to-previous vectors;
constant vectors or fabricated zero vectors must not be presented as a general
video solution. Version 1 also uses constant depth 0.5 and fixed 256x256 input.

## L. Primary result

`PERSISTENT_OFFLINE_DLSSG_2X_WORKER_WORKING`

## M. Remaining work

- add a real-video motion-vector provider and scene-cut/reset decisions;
- add caller-supplied depth where available and document quality tradeoffs;
- add negotiated dimensions and size-dependent feature/resource recreation;
- integrate the interpolation stage into decode/encode and UI flows;
- validate quality and performance at practical video resolutions;
- consider pipelining only after synchronous correctness is preserved;
- defer 3X/4X until the 2X product path is robust.

## N. Git

- offline proof checkpoint: `9ef7f8c81cec5e1780f7fb8605dd5ccaeefb14bc`
- persistent-worker source commit: the commit containing the implementation;
  exact SHA is recorded in the final task handoff because a commit cannot embed
  its own final content hash
- no proprietary runtime, generated frame, manifest, or SDK payload is tracked
- final push result is recorded in the task handoff
