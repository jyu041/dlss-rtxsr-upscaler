# DLSS5 v10 Isolated Adapter Contract — 2026-09-18

This document started by defining the process boundary for a Visual Enhancer v10
Feature-18 adapter. The normal application backend remains disabled. A later
milestone added a separately acknowledged, one-frame native execution path used
only by the bounded RTX 3070/3070 Ti research gate; no successful v10 hardware
execution is claimed until that gate is actually run and its evidence passes.

## Why a separate host

The validated v3 backend and Visual Enhancer v10 have materially different
runtime contracts:

- v3 uses the existing approved RenoDX/ReShade-style worker/runtime bundle;
- v10 exposes a dedicated ABI-6 Neural Rendering bridge;
- v10 treats D3D12/NGX state as process-lifetime state and deliberately avoids
  normal NGX shutdown/module unload after successful Feature-18 evaluation.

The v10 path therefore must not be implemented as a small extension of
`src/backends/dlss5.py`.

## Static parent-side gate

`src/backends/dlss5_v10_adapter.py` resolves the managed candidate directory
and calls the fail-closed v10 static inspector.

A host plan is produced only when:

- the three exact pinned DLL identities match;
- the binaries are x86-64;
- the complete project-required ABI-6 export surface is present;
- no configured static-review condition blocks the candidate.

The resulting `V10HostPlan` records:

- bridge DLL;
- caller shim;
- NVIDIA Neural Rendering runtime;
- exact expected hashes;
- isolated Python module;
- protocol version.

`execution_allowed` is hard-coded false.

The public `launch_host()` entry point raises `V10ExecutionDisabled`.

## Host process boundary

`src/backends/dlss5_v10_host.py` keeps normal `--serve` execution blocked.
It also contains an explicitly separate `--experimental-native-serve` mode
reachable only through the bounded client acknowledgement and fresh security
preflight. That mode is not wired into setup, startup, the UI, or the normal
DLSS 5 backend.

The non-native contract selftest remains available:

```powershell
python -m src.backends.dlss5_v10_host --contract-selftest
```

It validates the static Python ABI/protocol definitions and reports:

- `native_loaded=false`;
- `execution_allowed=false`;
- protocol identity;
- ABI version;
- struct sizes;
- required exports;
- expected file hashes.

`--serve` still exits with a blocked status. Native loading is reachable only
from `--experimental-native-serve`, which imports the isolated loader after the
bounded acknowledgement/security gates have passed.

## Protocol

`src/backends/dlss5_v10_protocol.py` defines protocol version 1.

Header:

```text
<4sHHII
magic        = "NR10"
version      = 1
command      = uint16
request_id   = uint32
payload_size = uint32
```

Payloads are bounded to 128 MiB. This is large enough for the upstream
7680×4320 RGBA8 boundary (126.6 MiB plus protocol metadata) while remaining a
hard transport cap.

Reserved commands:

- HELLO
- CREATE
- FRAME
- OUTPUT
- CLOSE
- ERROR

The protocol is transport scaffolding only. It does not yet define a native
frame-memory implementation.

## Protocol v1 payload contract

The first protocol generation is intentionally narrow: **host-memory RGBA8
only**. CUDA/NV12/P010 transport remains outside this milestone even though the
upstream bridge ABI can represent those formats.

CREATE is a canonical JSON object containing:

- input width and height;
- one exact upstream processing scale:
  `0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0`;
- style `0/1/2` = Default/Natural/Cinematic;
- ABI-6 Neural Rendering controls:
  intensity, NR passes, tone, structure, skin, color strength, tone
  preservation, face/skin protection, grain preservation, shimmer suppression;
- automatic-mask and NVOF-preference flags;
- literal transport declarations `memory_type=host` and
  `pixel_format=rgba8`.

The control limits are copied from the pinned upstream v10 validation logic:

- intensity/tone/structure: 0..2;
- skin structure: -1..2;
- color/tone-preservation/face-protection/grain/shimmer: 0..1;
- NR passes: integer 1..4.

Output geometry uses upstream's nearest-even rule after Lanczos pre-resize and
must remain at least 64×64 and within the 7680×4320 long/short-edge boundary.

FRAME payload is binary:

```text
int64 timestamp
uint8 reset
7 bytes reserved
width * height * 4 bytes tightly-packed RGBA8
```

OUTPUT payload begins with:

```text
uint32 width
uint32 height
int64  timestamp
int32  ngx_create_result
int32  ngx_evaluate_result
int32  cuda_result
int32  scene_reset
float  scene_score
uint64 upload_bytes
uint64 download_bytes
```

and is followed by exactly `width * height * 4` RGBA8 bytes.

This retains the Feature-18 result codes needed to distinguish successful
Neural Rendering from fallback/error behavior.

## Request ordering and poison semantics

The child HELLO message reserves request ID 0. Parent requests begin at 1:

1. exactly one CREATE;
2. zero or more consecutive FRAME requests;
3. one CLOSE.

Request IDs must be strictly consecutive. CREATE after CREATE, FRAME before
CREATE, repeated CLOSE, skipped IDs, truncated messages, invalid reset flags,
unknown commands, and payloads above the 64 MiB protocol limit are rejected.

Any future native timeout or native/ABI error poisons the process session.
After poison, no additional CREATE/FRAME request may be accepted. CLOSE remains
available as a terminal parent-side protocol action, after which the parent owns
process termination if the child fails to exit within the bounded grace period.

Current constants are deliberately conservative:

- host start timeout: 15 s;
- frame timeout: 30 s;
- close grace: 1 s.

These are contract values only at this milestone; the host still cannot execute
a v10 DLL.

## Non-native subprocess integration test

`src/backends/dlss5_v10_client.py` now exercises the real parent/child pipe
transport against an explicit `--protocol-selftest-server` mode in the host.

That simulator:

- reports `native_loaded=false` and `execution_allowed=false` in HELLO;
- validates the same CREATE/FRAME/CLOSE schemas and request ordering;
- supports only 1.0x FRAME echoing, so it cannot be mistaken for a resizing or
  Neural Rendering implementation;
- returns `-2147483648` for NGX create/evaluate/CUDA result fields as a
  reserved simulation sentinel;
- never loads a v10 DLL.

The parent supervisor uses real subprocess pipes and implements:

- 15 s bounded startup;
- 30 s bounded request round-trip;
- strict response request-ID matching;
- session poisoning on timeout/protocol/host error;
- owned-process termination after poison;
- 1 s bounded close grace.

The normal `start()` method remains blocked with `V10ExecutionDisabled`.
`start_protocol_selftest()` remains non-native, while
`start_native_experimental()` requires the exact
`BOUNDED_256_ONE_FRAME` acknowledgement and is reserved for the bounded
hardware validator.

## Offline native-loader review

The pinned upstream v10 implementation loads the bridge with Windows
`WinDLL`, binds the ABI surface, calls `dlss5nr_version()` and
`dlss5nr_frame_abi_version()`, and rejects a frame ABI other than 6 before
initialization.

`src/backends/dlss5_v10_native.py` now mirrors that binding plan without being
connected to the host:

- exact runtime static identity is rechecked immediately before any load;
- native loading is disabled by default and raises
  `V10NativeLoadDisabled`;
- `allow_native_load=True` is required even to reach the loader;
- the ABI-6 required function signatures are bound explicitly;
- runtime frame ABI is checked again after load;
- optional `dlss5nr_release_session` is bound if present;
- no NGX shutdown/unload routine is part of the isolated-host lifecycle plan.

The module is covered with fake-library tests. The normal production host path
does not load it; the bounded experimental host imports `load_bridge` only
after the explicit acknowledgement and fresh preflight have been validated.

This preserves a reviewed loader source while keeping native execution outside
the normal application path.

## Intended execution architecture

The later execution milestone should keep all of these inside one owned child:

1. load the exact pinned v10 bridge/caller/NVIDIA DLL set;
2. verify runtime ABI version 6 again at runtime;
3. create Feature-18 state;
4. process bounded frames;
5. retain NGX/driver modules for the lifetime of that child;
6. terminate the owned child rather than requiring unsafe NGX global teardown.

The parent process should own:

- timeout;
- process-tree termination;
- frame/request ordering;
- payload bounds;
- exact runtime identity;
- evidence capture.

This mirrors the project's existing use of supervised native helpers while
preserving v10's distinct lifecycle.

## Next gate before native execution

Before implementing the native-load portion:

1. define exact CREATE/FRAME payload schemas;
2. define RGBA8 host-memory frame limits and output geometry rules;
3. define error/result evidence fields, including NGX create/evaluate codes;
4. define timeout/poison semantics;
5. unit-test all protocol framing and malformed-message behavior;
6. perform an offline source review of the loader implementation.

Only then should the host gain a native-load code path, and that path should
remain opt-in for a bounded 256x256, one-frame, 1.0x RTX 3070 Ti validation.

## Additional bounded-hardware gate hardening

Before the first RTX 3070/3070 Ti native run, the bounded validator now also:

- requires the Defender/static preflight report to be no older than 24 hours;
- rejects missing, timezone-naive, stale, or unexpectedly future preflight timestamps;
- rechecks the exact runtime identity at execution time as before;
- records preflight age and Defender scan evidence in the hardware report;
- inspects the isolated host process tree after HELLO, CREATE, and the one FRAME;
- fails the experiment if the native host has spawned any descendant process.

The descendant-process check is an additional containment signal, not a general
sandbox. Direct network activity in the host process remains blocked by the
temporary exact-interpreter outbound firewall rule during the bounded run.

Additional pass criteria for the first bounded native run:

- CREATE must report bridge ABI 6 and the requested GPU ordinal;
- the selected GPU name must remain on the RTX 3070/3070 Ti path;
- host CLOSE must complete cleanly rather than falling back to forced termination;
- temporary firewall-rule removal is part of pass/fail: cleanup failure forces
  the overall report to FAIL and surfaces a manual-cleanup error.

## Current first-hardware-run gate

The bounded validator now fails closed unless all of the following are true:

- HELLO advertises exactly 256x256 input, 1.0x processing scale and one maximum frame;
- CREATE reports native loading, output size 256x256, bridge ABI 6, the requested
  GPU ordinal, and an RTX 3070/3070 Ti device name;
- the one FRAME returns exactly 256x256 RGBA8 bytes;
- both Feature-18 `ngx_create_result` and `ngx_evaluate_result` equal the
  bridge's NGX success value `1`;
- the rendered output shows a measurable Neural Rendering effect;
- no descendant process appears after HELLO, CREATE or FRAME;
- CLOSE completes normally without NGX global shutdown/module unload;
- the exact-interpreter outbound firewall rule is removed successfully.

This prevents a changed image, fallback path, or non-success NGX result from
being mistaken for a successful v10 compatibility result.

The reproducible local entry point is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_bounded.ps1 -Execute
```

That wrapper deliberately refreshes the candidate staging/static identity and
Microsoft Defender preflight **before** invoking the one-frame validator with
the exact `BOUNDED_256_ONE_FRAME` acknowledgement. It remains a developer
research command and is not called by `setup.bat` or `start.bat`.

## First bounded native v10 hardware result

The first bounded native Visual Enhancer v10 run completed successfully on
2026-09-19 on the RTX 3070 Ti.

Pinned candidate identity and preflight:

- archive size: `690203043` bytes;
- archive SHA-256:
  `394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515`;
- static audit passed before and after staging;
- Microsoft Defender custom scan returned clean;
- bounded-run preflight age was approximately `0.247` seconds.

Native CREATE evidence:

- `native_loaded=true`;
- output size `256x256`;
- bridge ABI `6`;
- bridge version `1.5.0-temporal-guides-frameabi-v6`;
- GPU `NVIDIA GeForce RTX 3070 Ti`, ordinal `0`;
- no descendant process after HELLO or CREATE.

The single reset FRAME also passed:

- `ngx_create_result=1`;
- `ngx_evaluate_result=1`;
- `cuda_result=0`;
- `scene_reset=1`, `scene_score=1.0`;
- upload/download payloads were each `786432` bytes;
- no descendant process appeared after FRAME;
- measured Neural Rendering effect was observed:
  - mean absolute difference `6.207366943359375`;
  - maximum absolute difference `52`;
  - changed-pixel ratio `0.9996490478515625`;
  - RMSE `8.218886375427246`;
  - input and output SHA-256 values differed.

The host returned `CLOSED`, the temporary outbound firewall rule was removed,
the final report status was `PASS`, and
`normal_backend_changed=false`. Total bounded-run time was approximately
`7.95` seconds.

This establishes **bounded v10 Feature-18 native compatibility on the tested
RTX 3070 Ti configuration**. It does not promote v10 into the normal
application backend, does not establish multi-frame temporal stability, and
does not replace the validated v3 path.

## Three-frame temporal milestone

The next bounded v10 milestone is now implemented as a **separate** experiment
rather than widening the already-proven one-frame path.

It uses:

- acknowledgement token `BOUNDED_256_THREE_FRAME`;
- host mode `--experimental-native-temporal-serve`;
- exactly three 256x256 / 1.0x frames;
- reset pattern `[true, false, false]`;
- the same fresh preflight, exact runtime identity, outbound firewall block,
  RTX 3070/3070 Ti restriction, ABI-6 check, process-tree inspection, clean
  CLOSE requirement and firewall cleanup requirement as the one-frame gate.

Each frame must independently return successful NGX create/evaluate evidence,
CUDA result 0, the expected timestamp and scene-reset state, and a measurable
Neural Rendering effect. Output hashes must be unique across the three-frame
sequence so stale/replayed output cannot satisfy the gate.

The reproducible entry point is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_temporal.ps1 -Execute
```

That command refreshes the static/Defender preflight before native execution and
writes `runtime/audit/dlss5-v10-temporal-hardware.json`.

### Three-frame temporal hardware result

The three-frame temporal gate passed on 2026-09-19 on the RTX 3070 Ti.

The refreshed candidate/preflight remained clean and exact:

- archive SHA-256:
  `394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515`;
- Microsoft Defender returned no threats;
- preflight age at execution was approximately `0.201` seconds;
- bridge ABI was `6`;
- bridge version was `1.5.0-temporal-guides-frameabi-v6`;
- GPU was `NVIDIA GeForce RTX 3070 Ti`, ordinal `0`.

The sequence used the required reset pattern `[true, false, false]`. All three
FRAME requests returned:

- `ngx_create_result=1`;
- `ngx_evaluate_result=1`;
- `cuda_result=0`;
- the expected timestamp and scene-reset state;
- a measurable Neural Rendering effect.

The two non-reset frames reported `scene_reset=0`, demonstrating that the
persistent native session accepted sequential temporal frames without forcing a
reset. All three output hashes were unique, so stale/replayed output did not
satisfy the gate. No descendant process appeared after HELLO, CREATE or any
FRAME. The host returned `CLOSED`, the temporary firewall rule was removed,
and the final report status was `PASS`. Total bounded-run time was
approximately `5.745` seconds.

This establishes **bounded three-frame temporal Feature-18 compatibility** on
the tested RTX 3070 Ti configuration. It is stronger evidence than the prior
single-frame result, but it still does not establish full-video robustness,
scene-cut handling, long-session stability, quality suitability, or production
readiness. The normal v10 application backend remains disabled.

## Sixteen-frame real-video temporal A/B milestone

The next v10 evidence gate is now implemented as a separate 16-frame
real-video A/B experiment. It still does not enable the normal v10 backend.

The command is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_video_ab.ps1 `
    -Execute `
    -Input "C:\path\to\clip.mp4"
```

Default `StartFrame` is 30 and can be overridden explicitly. The selected
source frames are center-square-cropped and area-resized to 256x256 RGBA8 so
the test does not stretch non-square input.

The exact same 16 source frames are then processed in two independently created
native sessions under acknowledgement `BOUNDED_256_VIDEO_AB_16`:

1. `persistent`: frame 0 uses `reset=true`; frames 1-15 use
   `reset=false`;
2. `reset-control`: every frame uses `reset=true`.

Both sessions retain the existing exact runtime identity, fresh static/Defender
preflight, RTX 3070/3070 Ti restriction, ABI-6 check, exact-interpreter
outbound firewall rule, per-frame NGX/CUDA checks, process-tree inspection,
stale-output detection, clean CLOSE requirement and firewall cleanup.

The validator additionally records:

- per-frame persistent-versus-reset comparison metrics;
- which non-initial frames differ between the two modes;
- source-delta error MAE/RMSE for each mode;
- enhancement-residual flicker MAE for each mode;
- persistent-minus-reset deltas for those temporal metrics;
- three source/persistent/reset review triptychs.

This gate intentionally does **not** declare the persistent result higher
quality based on one metric. Its pass criteria establish that both native paths
execute correctly and that persistent temporal state measurably influences
non-initial real-video outputs without stale replay. The metric deltas and
review images are evidence for the subsequent quality decision.

### Sixteen-frame real-video A/B hardware result

The real-video A/B gate passed on 2026-09-19 on the RTX 3070 Ti using
`trimmed.mp4`, source frames 30-45. The 640x480/~30-fps source was
center-square-cropped to 480x480 and area-resized to 256x256 RGBA8.

Both 16-frame native sessions passed all containment and execution checks:

- fresh Defender preflight passed with no threats;
- bridge ABI was 6 on the RTX 3070 Ti, GPU ordinal 0;
- all FRAME requests returned NGX create/evaluate success and CUDA result 0;
- all outputs were unique within each session;
- no descendant process appeared;
- both hosts returned `CLOSED`;
- firewall cleanup succeeded.

The baseline frame 0 was byte-identical between the two fresh reset sessions.
Every non-initial frame 1-15 differed between persistent and reset control, so
the v10 Feature-18 path is demonstrably retaining and using temporal state on
real video rather than merely accepting sequential calls.

This test does **not** establish that the persistent result is visually better.
On this short sample, the unwarped pixel-domain temporal metrics were higher
for the persistent path:

- source-delta/residual MAE mean: persistent `1.869203`, reset control
  `1.128326` (persistent minus reset `+0.740877`);
- source-delta RMSE mean: persistent `2.892242`, reset control `1.677198`
  (persistent minus reset `+1.215044`).

Those metrics do not compensate for motion and therefore are not a standalone
quality verdict. They are, however, a reason not to promote the persistent v10
path yet.

## Thirty-two-frame scene-cut/reset milestone

The next isolated gate is now implemented to test whether the explicit v10
reset flag actually clears temporal carry-over at a hard scene boundary.

The command is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_scene_cut.ps1 `
    -Execute `
    -Input "C:\path\to\clip.mp4"
```

The default window is 32 source frames beginning at frame 0. The existing
deterministic project scene-cut detector identifies hard cuts after the same
256x256 preprocessing used by the real-video A/B. A no-cut window fails rather
than being counted as scene-cut evidence.

The same frames are processed in three independently created sessions under
acknowledgement `BOUNDED_256_SCENE_CUT_32`:

1. `no-cut-reset`: reset on frame 0 only;
2. `scene-aware`: reset on frame 0 and every detected cut frame;
3. `reset-control`: reset on every frame.

At each detected cut, the scene-aware reset output must be byte-identical to the
reset-control output for the same source frame. This is a strict technical test
that the reset flag reproduces fresh-reset behavior and clears prior temporal
state. The harness also records whether no-reset carry-over changes the cut
frame, temporal metrics around each cut, and source/no-reset/scene-aware/reset
review panels.

### Thirty-two-frame scene-cut/reset hardware result

The scene-cut/reset gate passed on 2026-09-19 on the RTX 3070 Ti using
`trimmed.mp4`, source frames 0-31. The detector identified hard cuts at
frames 5 and 23.

All three native sessions passed execution and containment checks. Each produced
32 unique outputs, no frame was byte-identical to its input, no descendant
process appeared, each host returned `CLOSED`, and firewall cleanup succeeded.

The reset semantics were exact:

- the fresh frame-0 output matched reset control bit-for-bit in both comparison
  sessions;
- at cut frame 5, scene-aware reset matched reset control bit-for-bit while the
  no-cut-reset path differed with MAE `3.148956`, RMSE `5.177971`, maximum
  error `54`, and changed-pixel ratio `0.989349`;
- at cut frame 23, scene-aware reset again matched reset control bit-for-bit
  while the no-cut-reset path differed with MAE `3.936096`, RMSE
  `6.947761`, maximum error `55`, and changed-pixel ratio `0.969391`.

This establishes that the explicit v10 reset clears temporal carry-over at both
tested real scene boundaries rather than only changing a reported reset flag.

The global unwarped temporal diagnostic also moved in the expected direction
relative to never resetting at cuts:

- source-delta/residual MAE mean: no-cut-reset `2.584162`, scene-aware
  `2.433787`, reset control `2.380039`;
- source-delta RMSE mean: no-cut-reset `4.059786`, scene-aware `3.810563`,
  reset control `3.337175`.

These measurements remain motion-confounded and are not a visual-quality
ranking.

## 128-frame scene-aware soak milestone

The next isolated gate is a 128-frame real-video A/B soak. It compares:

1. a scene-aware temporal session reset on frame 0 and every detected hard cut;
2. an all-reset control over the exact same source frames.

The acknowledgement is `BOUNDED_256_SCENE_AWARE_128`. The normal application
backend remains disabled.

The gate preserves the existing runtime identity, Defender, firewall, RTX
3070-family, ABI-6, NGX/CUDA, process-tree, stale-output, CLOSE and cleanup
requirements. It also requires exact reset-control parity on frame 0 and every
detected cut, and requires temporal-state influence on at least one non-reset
frame.

In addition to the existing unwarped metrics, the soak records a
motion-compensated enhancement-residual flicker diagnostic. Backward optical
flow is estimated only from source luma, cut transitions are excluded, the
previous enhancement residual is warped into the current frame, and both source
alignment error and residual flicker are retained. This is diagnostic evidence
only; it does not automatically decide which mode has better visual quality.

The reproducible entry point is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_dlss5_v10_scene_soak.ps1 `
    -Execute `
    -Input "C:\path\to\clip.mp4"
```

The normal v10 backend remains disabled.

