# Real-Video DLSS-G 2X Backend

## A. Starting state

This milestone starts from the proven persistent offline worker at commit
`2059e6978334b5f139f79411db736a641582e0d7`. The earlier one-shot proof remains
at `9ef7f8c81cec5e1780f7fb8605dd5ccaeefb14bc`; neither commit was rewritten.
At the start, local `main` was two commits ahead of `origin/main`, which remained
at `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`.

The implementation was checkpointed as:

- `b8d8318`: NVIDIA Optical Flow motion provider and protocol v2;
- `c9312dd`: real-video DLSS-G 2X decode/interpolate/encode pipeline;
- `29e9103`: application and Gradio backend integration.

## B. Investigation findings

The requested read-only investigations were conducted as four independent
tracks by the main agent because no sub-agent execution facility was available
in this session.

### NVOF D3D12 design

The driver exposes API 5.0 through `nvofapi64.dll`. The D3D12 path uses
`NvOFGetMaxSupportedApiVersion`, `NvOFAPICreateInstanceD3D12`,
`nvCreateOpticalFlowD3D12`, capability/format queries, `nvOFInit`, registered
D3D12 resources, `nvOFExecuteD3D12`, explicit input/output fences, resource
unregistration, and `nvOFDestroy`. The plan was adopted directly.

### Existing video pipeline

The repository already used FFmpeg/PyAV, central output paths, a backend status
model, Gradio job cancellation/progress, and existing video render functions.
The new stage therefore uses those conventions rather than introducing another
media framework. DLSS-G remains a separate interpolation backend, not an RTX
VSR, DLSS SR, or DLSS Neural Rendering mode.

### Motion conversion

For previous frame A and current frame B, NVOF receives A as `inputFrame` and B
as `referenceFrame`. With bidirectional prediction, the backward output is B to
A, exactly the current-to-previous convention required by the proven DLSS-G
contract. Each signed S10.5 component is divided by 32 and encoded as IEEE FP16
in a tightly packed `DXGI_FORMAT_R16G16_FLOAT` field. No sign inversion or
sub-pixel offset is added.

### Timeline and audio

The stream order is `F0, G0.5, F1, G1.5, ...`. The default constant-frame-rate
policy duplicates the final real frame once: N inputs produce N-1 generated
midpoints and 2N encoded frames at 2x input FPS, preserving exact nominal
duration. The original audio stream is remuxed unchanged and is not sped up or
slowed down. A `short` policy is also available for a 2N-1 tail.

## C. NVOF architecture

`native/dlssg_sm86_offline/nvof_d3d12.cpp` dynamically loads the system copy of
`nvofapi64.dll` with `LOAD_LIBRARY_SEARCH_SYSTEM32`. No driver DLL is committed
or redistributed.

The NVOF instance reuses the worker's RTX 3070 Ti D3D12 device and direct queue.
Capability probing established:

- driver/client API version: `0x50` / `0x50`;
- GPU support: yes;
- 1x1 output grid: yes;
- bidirectional prediction: yes;
- advertised input DXGI formats: 87, 103, 61;
- selected input: `DXGI_FORMAT_B8G8R8A8_UNORM` (87);
- advertised output DXGI formats: 38, 36;
- selected flow output: `DXGI_FORMAT_R16G16_SINT` (38).

Input RGBA bytes are channel-swizzled while uploading to the reusable BGRA8
textures. Previous/current, forward/backward flow, upload, and readback
resources persist for the fixed-size session. NVOF waits on the direct queue's
completed upload fence and returns an NVOF output fence before readback.

A driver-lifetime hazard was found and fixed: registered D3D12 resources must
be unregistered and their application references released while the NVOF
session is still alive. Destroying the session first and then releasing the
resources caused an access violation on driver 610.62.

Dependency provenance and official SDK setup are documented in
`third_party/nvidia-optical-flow/README.md`. No SDK payload is tracked. The
official NVIDIA source baseline inspected was commit
`edb50da3cf849840d680249aa6dbef248ebce2ca`; the API-v5 D3D12 header used for
this development build came from an inspected temporary mirror at
`99e8d8eb8f269591e5e4bd5a7f3c248bbbc3a3b9` because NVIDIA's Windows package
download required sign-in. Production builds should use the official package.

## D. Flow contract

- Ordering: previous A, current B.
- NVOF prediction: BOTH.
- Consumed result: backward flow B to A.
- Direction supplied to DLSS-G: current to previous.
- Raw format: two signed 16-bit S10.5 components per pixel.
- Pixel conversion: `float(component) / 32.0f`.
- DLSS-G format: tightly packed little-endian R16G16 FP16.
- DLSS-G scale: `(1 / width, 1 / height)`.
- Grid: one vector per source pixel.
- Origin/sign: native top-left image ordering and unmodified NVOF sign.
- Edges: NVOF estimates are retained; no synthetic fill or silent zero-motion
  fallback is applied.

## E. NVOF validation

`--nvof-flow-test` used textured 256x256 frames with a square moving from x=64
to x=72. The backward-flow measurements were:

- moving-object mean: `(-8.1057, -0.0698)` pixels;
- moving-object median: `(-8.1250, -0.0938)` pixels;
- background mean magnitude: `0.3566` pixels;
- converted motion payload: 262,144 bytes;
- validation: pass.

This confirms the expected negative horizontal current-to-previous direction
without requiring every boundary pixel to equal exactly -8.

The loaded driver runtime was `C:\Windows\System32\nvofapi64.dll`, version
32.0.16.1062, SHA-256
`9A25A1E63B2F16FB4F8349A7CA3B39976CCD0F7140B7C8C8E4981BCB81491C51`.

## F. Persistent worker integration

Protocol v2 adds explicit motion modes:

- `EXTERNAL_R16G16_FLOAT`: the existing caller-supplied debug/regression path;
- `NVIDIA_OPTICAL_FLOW`: color-only requests with internal dense motion.

In internal mode, CREATE initializes NVOF at the requested dimensions. The
first frame after CREATE/RESET stores the real frame, supplies zero motion to a
reset Evaluate, and returns no midpoint. Each later frame runs backward NVOF,
converts the flow, performs one DLSS-G Evaluate, reads the generated midpoint,
and advances previous=current. The first NVOF pair after a history reset disables
temporal hints; later contiguous pairs permit them.

The fixed-size worker reuses all NVOF and DLSS-G resources. A changed CREATE
waits for completed synchronous work, releases the old feature and size-bound
resources, recreates NVOF and DLSS-G state, invalidates history, and keeps the
process and community runtime initialization alive.

The final persistent NVOF regression processed 16 real frames in one process
across two history sequences. Results: one Init, one CreateFeature, 16 Evaluate
calls, two reset-only results, 14 generated frames, and 14/14 unique generated
hashes. No interpolation-disable result occurred.

## G. Video pipeline

`src/video/dlssg.py` implements the production-facing sequence:

1. PyAV probes geometry, average frame rate, duration, frame count, and audio.
2. FFmpeg decodes tightly packed RGBA8 frames through a bounded pipe reader
   that handles partial reads and rejects truncated frames.
3. One persistent worker is created in internal-NVOF mode.
4. F0 is submitted as reset and emitted as the first real output.
5. Every later Fi yields and emits the midpoint before Fi.
6. FFmpeg encodes the stream at exactly twice the input frame rate.
7. The input audio stream and metadata are remuxed unchanged.

The CLI is `tools/dlssg_video.py`. It requires explicit paths to the native
worker, external community runtime, and official runtime directory. The
community runtime is never downloaded or bundled.

The default duplicate-terminal policy produces 2N output frames and preserves
nominal CFR duration. For the 16-frame 8 fps test, the output was 32 frames at
16 fps and remained exactly 2.0 seconds. For the 8-frame 1280x720 test, the
output was 16 frames at 16 fps and remained exactly 1.0 second. Both retained
audio.

## H. Dynamic dimensions

The worker accepts dimensions from 1x1 through 3840x2160. An in-process test
created 256x256, processed three frames, then recreated at 320x180 and processed
three more. It used one process, one community Init, two feature instances, six
Evaluate calls, and four generated outputs.

End-to-end video validation covered 256x256 and 1280x720. No Python application
restart, swapchain, or Present was used.

## I. Quality validation

### Deterministic 256x256 clip

- input/output: 16 / 32 frames;
- input/output FPS: 8 / 16;
- duration: 2.0 / 2.0 seconds;
- generated midpoints: 15;
- unique generated hashes: 15/15;
- generated frames identical to either neighbor: 0;
- audio preserved: yes.

For the final post-audit pass, midpoint MAD to its previous/current neighbors
ranged roughly from 4.64 to 6.14 in the uncompressed worker output. Encoded
validation again found every odd generated slot different from both adjacent
real frames. Contact triplets and manifests are under ignored
`runtime/dlssg_video`.

### Deterministic 1280x720 clip

- input/output: 8 / 16 frames;
- input/output FPS: 8 / 16;
- duration: 1.0 / 1.0 second;
- generated midpoints: 7;
- unique generated hashes: 7/7;
- generated frames identical to either neighbor: 0;
- audio preserved: yes.

The repository contains no non-sensitive natural-video fixture (`inputs`
contains only `.gitkeep`). Per task constraints, unrelated user directories
were not searched and no copyrighted test video was downloaded. Natural-video
visual validation therefore awaits a user-supplied clip; hashes and MAD prove
ordering/non-staleness, not perceptual quality.

## J. Performance

Mean measured timings (milliseconds per generated pair):

| Stage | 256x256 | 1280x720 |
|---|---:|---:|
| decode per input frame | 0.218 | 2.427 |
| NVOF upload | 0.638 | 3.583 |
| NVOF execute | 4.861 | 32.099 |
| CPU flow conversion | 0.518 | 6.555 |
| DLSS-G upload | 6.703 | 46.353 |
| DLSS-G Evaluate CPU | 0.328 | 0.380 |
| DLSS-G GPU wait | 0.727 | 1.344 |
| generated readback | 0.178 | 1.285 |
| native PROCESS total | 8.129 | 49.810 |
| encode pipe write per output | 0.155 | 1.100 |

Observed whole-command throughput, including process/runtime startup and final
encoding/remux, was about 5.00 output fps at 256x256 and 1.35 output fps at
1280x720. The current correctness-first design performs CPU flow readback and
conversion plus CPU RGBA transfers; these dominate the path at practical
resolution and are explicit optimization targets.

## K. Application integration

The application now registers a distinct `DLSS Frame Generation (2X)` mode.
It exposes:

- external community `version.dll` path;
- official NGX runtime directory;
- motion provider: NVIDIA Optical Flow;
- depth mode: Constant 0.5.

Backend diagnostics report whether all external paths are configured. Full
video render and bounded clip preview route through the new interpolation
pipeline; the single-frame preview explains that interpolation is temporal.
Progress/cancellation and central output naming follow existing application
conventions. Gradio validation used the repository-pinned 6.16.0 package in an
ignored project-local dependency directory; the global Gradio 5.29 install was
not modified.

Constant 0.5 depth is intentionally exposed as an experimental quality
limitation. The code does not pretend it is renderer-quality depth and does not
silently substitute fake motion when NVOF is unavailable.

## L. GPU health

Before the final regressions, the RTX 3070 Ti on driver 610.62 reported 39 C,
685 MiB / 8192 MiB VRAM, and 0% utilization. Afterward it reported the same
values. All Evaluate checks reported device removal reason `0x00000000`.

The narrow System/Application event window contained no nvlddmkm, Display,
WHEA, Application Error, or Windows Error Reporting events. New nvlddmkm Event
153: **NO**.

## M. Tests

- x64 Release native build with `/W4`: pass;
- native `--selftest`: pass;
- NVOF capability probe: pass;
- NVOF synthetic direction/conversion test: pass;
- external-motion persistent regression: pass;
- internal-NVOF 16-frame/two-reset regression: pass;
- in-process resize 256x256 to 320x180: pass;
- 256x256 video pipeline/encoded validator: pass;
- 1280x720 video pipeline/encoded validator: pass;
- Python and pinned-Gradio suite: 65 passed, 2 skipped;
- `git diff --check`: pass.

The native compiler still reports only the known pre-existing unused helper,
legacy `sprintf`, unused-parameter, and unreachable-code warnings. No generated
EXE/PDB, NVIDIA/community DLL, SDK header payload, log, raw frame, contact
sheet, or video is tracked.

## N. Primary result

`REAL_VIDEO_PIPELINE_IMPLEMENTED_AWAITING_NATURAL_CLIP_VALIDATION`

The technical backend is end-to-end functional on deterministic encoded video
at two tested resolutions, but the requested natural-video visual validation
could not be completed because the repository contains no suitable clip.

## O. Remaining quality work

- visually validate one user-supplied natural clip;
- replace constant depth with external or monocular depth;
- move S10.5-to-FP16 flow conversion and preferably decode/input transfer onto
  the GPU;
- profile and optimize 720p/1080p resource movement;
- expand resolution/codec/audio-container coverage;
- evaluate 3X/4X only after the 2X real-video path is robust.

## P. Git

The source work is committed on local `main`. The community runtime, NVIDIA
driver/runtime DLLs, SDK payloads, and generated media remain external/ignored.
The final local HEAD, origin state, and push result are recorded in the task
completion message after the report commit and single push attempt.
