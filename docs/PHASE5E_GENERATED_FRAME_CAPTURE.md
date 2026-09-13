# Phase 5E — Generated-Frame Capture

## Result

`GENERATED_RESOURCE_NOT_ACCESSIBLE`

The known-good Phase 5C Streamline/DLSS-G path remains intact, but the public
Streamline contract does not expose an application-readable generated-frame
resource. No speculative swapchain hook was added and no Phase 5E live capture
run was performed.

## A. Known-good regression

The preserved Phase 5C build established:

- DLSS-G supported: YES
- DLSS-G feature created: YES
- DLSS-G active: YES
- requested generated frames: 1
- Streamline state transition: `disabled` → `enabled`, `numFramesToGenerate=1`
- process exit: 0
- GPU health: retained

The Phase 5C tree was not modified. A separate copy was created at:

`C:\Users\mark\Desktop\dlss-community-research\Streamline_Sample_MFGCapture`

The Phase 5C executable/runtime set was preserved. Phase 5C’s executable SHA
was `440F7A14166C61EBED19A30F96A354BE2726D7CB6E70B013183B9FF5B2AC6B0F` and
the donor remained pinned at
`c88b208e3f8f12e86a261f06aef1da3a77adef27`.

## B. Capture boundary

The relevant official source/API evidence is:

- `Streamline/include/sl_hooks.h`: public hooks include
  `IDXGISwapChain::Present`, `Present1`, `GetBuffer`, and
  `GetCurrentBackBufferIndex`.
- `Streamline/docs/ProgrammingGuideDLSS_G.md`: DLSS-G tags backbuffer, depth,
  motion vectors, and optional HUD-less/UI resources; the actual backbuffer
  pointer may be null because Streamline knows the presented backbuffer.
- The same guide states that all tagged buffers are consumed at
  `Swapchain::Present`.
- With DLSS-G enabled, Streamline renders through an off-screen path and the
  host has no direct access to swapchain buffers; the plugin uses an extra
  presentation queue and asynchronous SL pacer.
- `Streamline/include/sl_dlss_g.h`: `DLSSGState` exposes status, maximum frame
  count, frames-actually-presented telemetry, and an input-processing fence,
  but no generated-output `ID3D12Resource` or output callback.
- The sample’s `SLWrapper::TagResources_DLSS_FG` tags only the backbuffer
  semantic, normally with a null resource pointer.
- DLSS-G is driven by the swapchain Present marker; the sample does not call
  `slEvaluateFeature` for DLSS-G.

Therefore the generated image is an internal/proxy/interposer-owned
presentation result. The sample’s outer `DeviceManager_DX12::Present()` call
is not a valid generated-image capture boundary: copying its known host
resource before that call captures the real application frame, not the
generated frame. Public Streamline APIs do not provide a post-generated-frame
resource callback.

## C. Frame discrimination

No defensible image-level frame discriminator is available in the public
contract. `slDLSSGState::numFramesActuallyPresented` can report the number of
frames presented since the last state query and NVIDIA documents that one
generated frame normally yields a value of 2 per application frame. It does
not identify an image resource or provide per-present frame IDs that can be
used to read back the generated image.

The SL pacer may drop an interpolated frame when presents are out of sync, so
alternating host Present calls would not be a valid classifier. A native
swapchain hook at the wrong layer would either see only the application’s
outer Present or would lack a safe association between internal pacer presents
and the generated resource.

## D. D3D12 resource/ownership status

- Generated resource pointer: not exposed
- Generated resource format/dimensions: not exposed as an application resource
- Generated resource state: not exposed
- Producer queue: internal Streamline/DLSS-G presentation path; not exposed
- Ownership: Streamline/interposer/pacer-owned while generation is active
- Public copy source: none

Consequently, there is no valid `CopyResource`/`CopyTextureRegion` sequence to
implement from the public source-visible contract. In particular, blindly
calling `GetBuffer` on the application-facing swapchain would not establish
that the returned resource is the generated image.

## E. Copy/readback

Not reached. No copy was submitted, no fence was created for capture, no map
occurred, and no CPU image bytes or hash were produced. This is intentional:
the available host-side resource is not proven to be the generated resource.

## F. Live attempt

- Executed: NO
- Attempts: 0
- Retries: 0
- Reason: the required generated-resource/capture boundary is absent from the
  public Streamline API, and a host-side Present copy would fail the
  generated-versus-real criterion.
- Last successful stage: static/source contract determination
- GPU work in Phase 5E: NONE

No provider, architecture, Streamline runtime, or known-good executable was
changed. No live run was used to guess at an unsafe capture boundary.

## G. Hidden-swapchain feasibility

The working contract requires a real DXGI swapchain and `Present()` for DLSS-G
activation/pacing. A hidden or minimized HWND may be viable as a host detail,
but it does not solve the missing generated-resource ownership problem. The
least intrusive eventual arrangement is a hidden/minimized DXGI swapchain plus
a separately proven post-pacer/native-present capture mechanism, if one can be
established from Streamline internals or an officially supported integration
surface.

The following cases remain unproven and were not experimentally run:

- hidden HWND
- minimized HWND
- borderless off-screen HWND
- 1x1 swapchain

## H. Required next investigation

The next work must obtain a source-auditable capture boundary that is actually
inside or after Streamline’s internal presentation/pacer path, for example an
official callback or a fully understood source-built Streamline modification
that exposes the generated presentation resource. It must establish resource
identity, queue ownership, state, lifetime, and real/generated ordering before
any CPU copy is attempted.

## I. Primary classification

`GENERATED_RESOURCE_NOT_ACCESSIBLE`

Next step: `FIX_EXACT_CAPTURE_BOUNDARY` (not executed).

## J. Safety/Git

- No Desktop Duplication, BitBlt, or screen scraping used.
- No driver, provider, registry, HAGS, TDR, or GPU changes.
- No ReShade.
- No 3X/4X testing.
- No commit.
- No push.
