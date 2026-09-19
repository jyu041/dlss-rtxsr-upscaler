# DLSS5 v10 Experimental Application Hardware Evidence — 2026-09-19

This record covers the application-facing Visual Enhancer v10 path introduced by
PR #27. It is distinct from the earlier bounded research gates: both runs below
used `tools/run_dlss5_v10_app_smoke.ps1`, which refreshes the pinned
static/Defender preflight and then renders through the same
`render_dlss5_v10()` implementation used by the UI.

## Scope

Tested machine:

- GPU: NVIDIA GeForce RTX 3070 Ti
- GPU ordinal: 0
- bridge ABI: 6
- bridge version: `1.5.0-temporal-guides-frameabi-v6`
- application pixel format: SDR RGBA8
- processing scale: 1.0x
- host memory path
- caller-owned scene resets

Pinned v10 archive:

- size: `690203043` bytes
- SHA-256: `394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515`

Before each application render, the wrapper repeated the exact archive/static
identity checks, staged the candidate, and required a clean Microsoft Defender
scan. Native execution remained separate from the preflight report itself.

## 640x480 application smoke

Input: owned local `trimmed.mp4`.

Result:

- 90 frames processed
- 640x480
- measured end-to-end rate: approximately 9.52 fps
- source audio preserved
- four hard scene cuts detected
- five resets total (initial reset plus four cut resets)
- H.264 NVENC output
- `experimental_backend=dlss5-v10`
- `processing_scale=1.0`
- isolated host returned `CLOSED`
- firewall containment completed
- wrapper emitted `DLSS5_V10_APP_VIDEO_PASS`
- wrapper emitted `DLSS5_V10_APP_SMOKE_PASS`

The renderer is fail-closed: reaching PASS means every processed frame satisfied
its NGX create/evaluate success, CUDA result, timestamp, geometry, payload-size,
and expected reset-state checks, and no unexpected host descendant process was
accepted.

## 1920x1080 ceiling smoke

A one-second 1920x1080 test source was created from the same owned 640x480 clip
by scaling the 4:3 image to 1440x1080 and padding horizontally to 1920x1080.
This tests the advertised application geometry ceiling without stretching the
source aspect ratio.

Result:

- 30 frames processed
- 1920x1080
- measured end-to-end rate: approximately 2.85 fps
- source audio preserved
- one hard scene cut detected
- two resets total (initial reset plus the detected cut)
- H.264 NVENC output
- `experimental_backend=dlss5-v10`
- `processing_scale=1.0`
- application contract reported max long edge 1920 and max short edge 1080
- bridge ABI 6 initialized on the RTX 3070 Ti
- isolated host returned `CLOSED`
- firewall containment completed
- wrapper emitted `DLSS5_V10_APP_VIDEO_PASS`
- wrapper emitted `DLSS5_V10_APP_SMOKE_PASS`

## Conclusion

The explicit v10 application integration is hardware-validated on the tested
RTX 3070 Ti for its current 1.0x SDR RGBA8 boundary, including the advertised
1920x1080-equivalent maximum geometry. This evidence does not establish
official NVIDIA RTX 30-series DLSS 5 support, native output scaling above 1.0x,
cross-GPU compatibility, or perceptual superiority over v3 or other backends.
The mode remains explicit, experimental, fail-closed, and separate from the
validated v3 default path.
