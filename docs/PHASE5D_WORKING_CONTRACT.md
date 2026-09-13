# Phase 5D — Known-Good Ampere DLSS-G Contract

## A. Known-good status

The Phase 5C reference is the NVIDIA Streamline Sample, with the embedded
source-built `MFGAmpereUnlock-RenoDx` core. It completed one bounded run with
DLSS-G explicitly enabled and one generated frame requested. The donor logged
provider preparation, feature creation, and active generation; Streamline
logged the interpolation transition to `eOn` with `numFramesToGenerate=1` and
the process exited with code 0. This is the working reference contract for the
Ampere experiment.

- GPU: NVIDIA GeForce RTX 3070 Ti, native architecture `0x170`
- Compatibility architecture: `0x190`
- Provider target: SM86
- Streamline: `2122257e0fce486f91b385aa63b9a09b0a34b363` (v2.14.1)
- Sample base: `0bb8bf3ee80ce8d6b53688c2e237ac0981ce2f6c`
- Donor: `c88b208e3f8f12e86a261f06aef1da3a77adef27`
- ReShade: not used

The exact Phase 5C executable and runtime set were preserved; no additional
live execution was required in Phase 5D.

## B. Complete 2X call-order contract

| Order | Source/function | Timing and dependency | Mandatory for 2X |
|---:|---|---|:---:|
| 1 | `src/main.cpp`: `main` / command-line parsing | Process starts; `-mfg-ampere`, `-DLSSG_on`, and `-DLSSG_numFrameToGenerate 1` are parsed | Yes |
| 2 | `mfg_ampere::Initialize` | Embedded donor initializes before Streamline; installs loader/interposer/NGX observation hooks | Yes |
| 3 | `SLWrapper::Initialize_preDevice` in `src/SLWrapper.cpp` | Loads `sl.interposer.dll`, sets D3D12 preferences, requests `kFeatureDLSS_G` and Reflex, calls `slInit` | Yes |
| 4 | `CreateWindowDeviceAndSwapChain` | Creates the visible sample HWND, D3D12 adapter/device, and DXGI swapchain | Yes for this host; hidden HWND remains to be tested |
| 5 | `SLWrapper::SetDevice_nvrhi` / `SetDevice_raw` | Registers the D3D12 device with Streamline using `slSetD3DDevice` | Yes |
| 6 | `SLWrapper::Initialize_postDevice` / `UpdateFeatureAvailable` | Queries feature requirements and `slIsFeatureSupported` against the selected adapter | Yes |
| 7 | donor NVAPI/provider maintenance | Binds the physical GPU, confirms Ampere, discovers the mapped DLSS-G provider, retargets 70 fatbins and hides 31 cubins | Yes before DLSS-G requirements/Create |
| 8 | donor NGX bridge | Hooks/observes requirements, capability, Create, Evaluate, and provider loading; exposes `0x190` only for the Ampere DLSS-G path | Yes |
| 9 | `StreamlineSample::Animate` / per-frame setup | Builds `sl::Constants`, including frame token, matrices, jitter, reset, dimensions, and motion-vector scale | Yes |
| 10 | `SLWrapper::TagResources_General` | Tags depth, motion vectors, and pre-UI/HUD-less color, valid until Present | Yes |
| 11 | `SLWrapper::TagResources_DLSS_FG` | Tags the backbuffer semantic; the actual pointer is optional because SL knows the presented backbuffer | Yes |
| 12 | `StreamlineSample.cpp`: DLSS-G setup | Calls `slDLSSGGetState`, constructs options, sets `mode=eOn`, `numFramesToGenerate=1`, and calls `slDLSSGSetOptions` | Yes |
| 13 | Reflex path | Reflex availability is required by the sample’s scripted enable path; mode is promoted from off when DLSS-G is requested | Yes in this sample |
| 14 | command-list close/execute and Present | Host submits the rendered frame; Streamline’s common plugin runs its present path | Yes |
| 15 | native DLSS-G Create/Evaluate | Occurs inside Streamline/NGX behind the Present integration, not via host `slEvaluateFeature` | Yes |
| 16 | SL pacer | Schedules the real frame and generated interpolation frame asynchronously | Yes |
| 17 | `slDLSSGGetState` / `slFreeResources` / `slShutdown` | State/fence accounting and orderly release at shutdown | Yes for robust repeated operation |

Important distinction: DLSS-G does not use a normal Streamline
`slEvaluateFeature` call. NVIDIA’s guide states that the existing swapchain
Present marker is the DLSS-G integration point.

## C. Runtime stack

All paths below are from the Phase 5C sample `_bin` directory unless stated
otherwise. The matched Streamline files were not mixed with the older Phase 4
provider.

| Module | Canonical path / version | SHA-256 | Role |
|---|---|---|---|
| `StreamlineSample.exe` | `C:\Users\mark\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere\_bin\StreamlineSample.exe` | `440F7A14166C61EBED19A30F96A354BE2726D7CB6E70B013183B9FF5B2AC6B0F` | Host |
| `sl.interposer.dll` | sample `_bin`, 2.14.1.0 | `8C87C9499461DA561EDD529AA9BF7831D67D7B94EBB1C1A5ED54EF4934E1EA4C` | Streamline API/DXGI interposer |
| `sl.common.dll` | sample `_bin`, 2.14.1.0 | `82924A8954DD671E09351C5DE0EB87AD0EB25B944CC9F9AB955CA1D9950DE15D` | Common Streamline services |
| `sl.dlss_g.dll` | sample `_bin`, 2.14.1.0 | `F4A6B2B14DCC0B1485989E430D3B4E3A44AC1800B92BA1AD74F476E64FB2B09C` | DLSS-G plugin |
| `sl.reflex.dll` | sample `_bin`, 2.14.1.0 | `0CE9725E3E03EA9E7F81D008B57F33EE365973D2E349131C8B1C3E3378FE2DB0` | Reflex plugin |
| `sl.pcl.dll` | sample `_bin`, 2.14.1.0 | `F13D51CFA05F4CD514DF2026049E2DB8ADF359221713170AD386FD499915B582` | PCL support |
| `nvngx_dlssg.dll` | sample `_bin`, 310.9.1 | `FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82` | NGX DLSS-G provider |
| `nvapi64.dll` | `C:\Windows\System32\nvapi64.dll`, 32.0.16.1062 | `97F9CDF75AFA7431128A4B126FE8D6F36824C03E8CCFA09AC6AE687E0444B8A9` | NVAPI shim |
| `nvapi64_impl.dll` | NVIDIA DriverStore implementation, 32.0.16.1062 | `C129247C3F70BFCA49D3F16B28A02D5EE115E541B9F375F154F481A45B35F087` | NVAPI implementation owner |

The Streamline log showed the provider loaded from the sample directory and
reported version `310.9.1`. Exact module load sequencing is partially hidden
by Windows/Streamline, but the observed dependency order is interposer first,
then DLSS-G plugin/provider during feature discovery and Present setup.

## D. Provider contract

The donor’s loader/provider maintenance must be active before DLSS-G feature
requirements and before the first capability/Create path. The provider may be
loaded lazily by Streamline; therefore the donor keeps loader hooks active and
prepares the mapped module synchronously when it appears, with a second
maintenance pass around requirements/capability/Create as needed.

Observed Phase 5C preparation:

- provider qualification: one provider
- PTX/fatbin retargets: 70 (`sm_89` → `sm_86`)
- incompatible cubins hidden: 31
- provider architecture gates: donor requirements path adjusted; exact site
  count was not emitted by this sample build
- temporal preparation: donor initialization path retained its provider
  qualification ordering; no separate 3X/4X experiment was performed
- disk mutation: none; edits were process-local mapped-image edits

The provider is not an application output. It is a prerequisite for the
Streamline/NGX capability and Create/Evaluate paths.

## E. Resource contract

The sample’s authoritative implementation is in
`Streamline_Sample_MFGAmpere/src/SLWrapper.cpp` and
`Streamline_Sample_MFGAmpere/src/StreamlineSample.cpp`.

| Semantic | Sample resource / format | Extent/state/lifetime | Required |
|---|---|---|:---:|
| Final color/backbuffer | DXGI swapchain backbuffer; pointer is normally omitted from the FG tag | Intercepted automatically by Streamline’s swapchain; backbuffer tag carries optional subrect | Yes |
| Depth | `m_RenderTargets->Depth`; sample render-target format/state | Render extent; tagged `eOnlyValidNow` in the general sample path | Yes |
| Motion vectors | `m_RenderTargets->MotionVectors`; sample motion-vector format | Render extent; tagged `eValidUntilPresent` | Yes |
| HUD-less color | `m_RenderTargets->PreUIColor` | Full display extent; `eValidUntilPresent` | Recommended and used |
| UI color/alpha | Optional sample UI resource path | Full display extent; `eValidUntilPresent` | Optional; sample has a tag helper |
| UI alpha | Optional alternative UI resource | Full display extent; `eValidUntilPresent` | Optional |
| Exposure | No dedicated DLSS-G exposure tag observed | Tone mapping is performed by the sample before final display | Not a DLSS-G required tag |

The official guide identifies only backbuffer, depth, and motion vectors as
required for generation; Hudless and UI improve interpolation quality.

The sample tags resources before final blit and Present. Streamline retains
`eValidUntilPresent` resources until the Present boundary. It explicitly uses
`eOnlyValidNow` for depth in the D3D sample’s general tagging path; a future
video backend should choose lifetimes based on whether its buffers remain valid
until Present.

## F. Frame and per-frame contract

The sample fills `sl::Constants` once per frame before tagging:

- frame token: acquired through Streamline’s current frame-token mechanism;
- camera aspect ratio and vertical FOV;
- camera near/far (`near` from sample constant, `far=200`);
- camera position, forward, up, right;
- view-to-clip and inverse clip-to-view matrices;
- clip-to-previous-clip and inverse previous mapping;
- jitter offset from the planar view;
- `mvecScale = {1/renderWidth, 1/renderHeight}`;
- `cameraMotionIncluded = true`;
- `motionVectors3D = false`;
- motion-vector invalid value `FLT_MIN`;
- depth inversion flag;
- reset flag on a new pass;
- rendering/display dimensions through the viewport/resource extents;
- DLSS-G options: `mode=eOn`, `numFramesToGenerate=1`, and the sample’s
  retain-resources flag.

The sample advances the frame token and previous-view/camera state as part of
its frame loop. The frame index must correspond to the presented frame and to
Reflex Present markers. Reset must be asserted for the first frame after a
history discontinuity, resize, or scene cut. Matrices are row-major and should
not contain jitter baked into the matrix; jitter is supplied separately.

For generated-frame timing, NVIDIA documents that a 2X configuration presents
one real frame plus one interpolated frame per application Present in the
normal case. The interpolated frame may be dropped by the pacer if presents are
out of sync, so exact 2N output must be measured rather than assumed.

## G. Generated-frame location

Classification: `NO_SUPPORTED_DIRECT_CAPTURE`.

Evidence:

1. The official Streamline DLSS-G guide says the final color is intercepted
   automatically through the Streamline swapchain.
2. With DLSS-G enabled, the guide states that the host renders off-screen and
   has no direct access to swapchain buffers; Streamline performs an additional
   copy and manages an extra presentation queue.
3. DLSS-G intercepts `IDXGISwapChain::Present` and runs its asynchronous SL
   pacer. The sample does not receive a generated-frame `ID3D12Resource` from
   `slDLSSGGetState`, `slDLSSGSetOptions`, or `slEvaluateFeature`.
4. The public headers expose state counters and a completion fence for input
   lifetime, but no generated-output texture callback.

Therefore the generated frame is an internal/proxy/interposer-owned
presentation result, not an explicit application-owned output texture. The
sample’s `slDLSSGGetState::numFramesActuallyPresented` is the supported
telemetry for how many frames were presented since the previous query, but it
does not provide their image bytes.

## H. Readback feasibility

There is no supported direct texture readback path in the official public
Streamline API. A normal `CopyResource` from the application’s rendered color
buffer would capture the real application frame, not the generated frame.

The shortest plausible capture route is a process-local, D3D12 swapchain/present
instrumentation layer that observes the Streamline-managed presentation path
and copies the actual presented backbuffer into a readback resource before the
present operation relinquishes it. This is a new capture mechanism, not a
Streamline DLSS-G output API, and it must establish:

- which proxy/native swapchain interface is presented;
- the current backbuffer index via `GetCurrentBackBufferIndex`;
- resource state before the copy;
- a copy command and fence on the correct presenting queue;
- frame classification/order between real and interpolated presents;
- lifetime safety while the SL pacer owns asynchronous presentation.

Because the official guide warns that the host does not directly own the
swapchain buffers while DLSS-G is on, this capture path is not yet proven safe.
Desktop/screen capture is explicitly not required or selected, but would be a
separate fallback rather than a source-auditable texture contract.

## I. Headless/offscreen feasibility

| Requirement | Classification | Evidence |
|---|---|---|
| D3D12 device | MANDATORY | Streamline sample registers a D3D12 device with `slSetD3DDevice` |
| DXGI swapchain | MANDATORY for this DLSS-G path | DLSS-G’s activation and generation boundary is Present/swapchain interception |
| `Present()` | MANDATORY | `slDLSSGSetOptions` takes effect on the next Present; the plugin schedules generated frames there |
| HWND | LIKELY MANDATORY for the current sample | Current host uses `CreateWindowDeviceAndSwapChain`; hidden/minimized behavior is untested |
| compositor/display output | UNKNOWN / likely not semantically required | The pacer operates in-process, but the sample contract was not tested without a normal window/display |
| Reflex | MANDATORY in the sample’s enable path | Sample requires Reflex availability before setting DLSS-G on |
| HAGS | UNKNOWN on this machine | HAGS was not changed or reliably resolved; Phase 5C completed without a reported HAGS failure |
| visible presentation | NOT_REQUIRED in principle, but unproven for this stack | The API is swapchain-based; a hidden/offscreen swapchain remains the practical test target |

The appropriate next host is therefore a hidden/minimized swapchain only after
the capture and presentation ownership rules are implemented and tested.

## J. Backend architecture

Selected architecture: `STREAMLINE_HIDDEN_SWAPCHAIN_BACKEND`.

Reason: the known-good contract depends on Streamline’s D3D12 swapchain
Present/pacer path, while the target product needs image bytes rather than a
screen. A small hidden-window D3D12 host preserves the proven Streamline call
order and supplies a controlled swapchain for a future process-local capture
layer. Direct raw NGX would discard the contract that made Ampere work.

This selection does not claim that hidden-window generation or backbuffer
capture has already been proven. Those are the remaining implementation gates.

## K. Video-backend design

Initial product mode: 2X only.

- Input: two consecutive RGBA frames plus motion vectors, depth, camera
  constants, reset state, and monotonically advancing frame metadata.
- Host: persistent native Streamline process because initialization/provider
  qualification is expensive and the Streamline swapchain/pacer is stateful.
- Processing: submit frame A, then frame B with the correct temporal constants
  and resource tags; keep all tagged resources alive through the relevant
  Present/fence boundary.
- Output: capture the one generated midpoint from the Streamline-managed
  presentation path, then return image bytes to the video assembly layer.
- Assembly: `A, generated(A,B), B, generated(B,C), C, ...`.
- Protocol: a robust framed IPC or named-pipe protocol with an explicit READY
  handshake may be used later; the old fragile stdin worker must not be reused.
- Fallback: if provider qualification, Streamline support, state, Present, or
  capture fails, report a structured backend error and fall back to the existing
  video path.

## L. Usability gap to `MFG_BACKEND_2X_USABLE`

1. Build a clean hidden/minimized D3D12 Streamline host with the exact Phase 5C
   initialization and donor/provider mechanism.
2. Add a source-auditable capture layer for the Streamline-managed presenting
   resource; prove resource identity, state transitions, queue ownership, and
   fence completion.
3. Capture and classify real versus generated Present events; validate ordering
   and timestamp placement around the midpoint.
4. Feed real video frame pairs rather than the sample scene and validate motion
   vector convention/scale, depth, reset, matrices, and frame history.
5. Expose raw-byte output and verify dimensions, format, hashes, and nontrivial
   image statistics.
6. Keep the provider/runtime stack version-pinned and ensure no NVIDIA binary
   is committed or modified on disk.
7. Run at least 100 consecutive frame pairs without crash, device removal,
   TDR, or driver reset.
8. Measure initialization, per-frame latency, VRAM overhead, and 8 GB feasibility
   at 1080p/1440p/4K. No local benchmark was performed in Phase 5D.
9. Add fallback/error reporting and a robust READY/request/response lifecycle.

## M. Next step

`IMPLEMENT_HIDDEN_SWAPCHAIN_CAPTURE` (not executed).

## N. Safety and Git

- No driver, provider, registry, HAGS, TDR, voltage, power, or GPU settings
  were changed.
- No downloaded opaque binary was executed.
- No commit.
- No push.
