# DLSS-G MFG, performance, and preview validation

## Status

This work is deliberately recorded as a partial result.  The RTX 3070 Ti
validated 2X path remains healthy and the before/after clip preview is
implemented.  The generalized 3X request was sent to the installed community
runtime, but it returned `InterpolationDisabled` before producing a frame.
4X was not attempted after that failure.  Therefore neither 3X nor 4X is
classified as working.

* `DLSSG_BEFORE_AFTER_CLIP_PREVIEW_WORKING`
* `DLSSG_3X_MFG_NOT_VALIDATED`
* `DLSSG_4X_MFG_NOT_TESTED`
* `DLSSG_PIPELINE_PERFORMANCE_PARTIALLY_OPTIMIZED`

## Starting baseline and copy/synchronization audit

The starting validation at commit `f18d81899ae2b69c794ec8ea439e67cfd69efd5a`
reported native 2X PROCESS medians of about 63.7 ms at 640x480 and 221.0 ms
at 1920x1080.  It attributed most of the latter to NVOF, CPU flow conversion,
separate DLSS-G input uploads, and synchronous waits.

The present worker still has this dependency chain:

```text
CPU RGBA previous/current
  -> two D3D12 uploads for NVOF
  -> NVOF backward flow (CURRENT -> PREVIOUS)
  -> GPU-to-CPU R16G16_SINT readback
  -> CPU S10.5-to-R16G16_FLOAT conversion
  -> CPU-to-GPU DLSS-G motion upload

CPU current RGBA -> separate DLSS-G colour upload
DLSS-G Evaluate -> CPU fence wait -> output readback
```

Resources are persistent per resolution, but each group still has separate
NVOF and DLSS-G colour uploads and CPU-visible flow.  This is the remaining
1080p bottleneck.  A GPU-resident NVOF-to-motion conversion and shared colour
resource require a deeper D3D12 resource/queue integration and were **not**
claimed or shipped here.

## Change made to the production path

Normal worker processing no longer computes sampled flow percentiles,
variance, and other distribution statistics after the required flow readback.
The standalone NVOF direction harness retains those diagnostics.  This avoids
extra CPU allocation, sampling, square roots, and selection work during a
normal render, while preserving motion convention and scene-cut behavior.

The generalized protocol is version 4.  `CREATE.generatedCount` is one, two,
or three; `PROCESS` returns an unambiguous ordered concatenation whose byte
count must equal `generatedCount * width * height * 4`.  The Python client
splits it into `ProcessResult.outputs`.  The video renderer uses the same
loop for 2X, 3X, and 4X, emits output FPS multiplied by the selected factor,
uses source holds at cuts, and writes `multiplier - 1` terminal holds for its
exact-CFR policy.

## Measured 2X results

All figures below are medians of 14 generated groups from the sequential,
deterministic persistent-worker harness on an NVIDIA GeForce RTX 3070 Ti,
driver 610.62.  These are CPU-side stage measurements, not D3D12 timestamp
query GPU measurements.  They do not include decode, encode, or full-video
end-to-end FPS, so they must not be compared directly with upstream model-only
inference timings.

| Resolution | NVOF upload | NVOF execute | flow conversion | DLSS-G input uploads | DLSS-G wait | output readback | native PROCESS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 256x256 | 0.789 ms | 6.287 ms | 0.399 ms | 8.535 ms | 1.589 ms | 0.212 ms | 11.129 ms |
| 1280x720 | 6.961 ms | 78.198 ms | 4.983 ms | 101.544 ms | 21.194 ms | 3.226 ms | 128.628 ms |
| 1920x1080 | 11.493 ms | 160.034 ms | 11.061 ms | 203.684 ms | 34.770 ms | 6.815 ms | 246.610 ms |

The saved earlier 256x256 run using the same harness had a 18.919 ms median;
the new run observed 11.129 ms.  That is encouraging but is only a
single-run, uncontrolled comparison and is not a claim of a 2X speedup.
At 1080p the measured result remains above the requested target and even
above the earlier natural-video figure under a different workload.  The next
high-value work is the unimplemented GPU-resident motion path, not further
micro-optimisation.

## Multi Frame Generation validation

The worker passes the expected `MultiFrameCount` and sequential
`MultiFrameIndex` values to the existing DLSS-G option setup:

| Multiplier | generated count | requested indices |
| --- | ---: | --- |
| 2X | 1 | 1 |
| 3X | 2 | 1, 2 |
| 4X | 3 | 1, 2, 3 |

2X was revalidated with 14 unique generated synthetic outputs across two
history sequences.  `OUTPUT_DISABLE` was zero; the worker reported no device
removal; the NVOF direction test measured object mean `(-8.1057, -0.0698)`
and median `(-8.1250, -0.0938)`.

The first live 3X request returned native status `-9` (`InterpolationDisabled`)
and produced no usable generated frame group.  It did not reset the driver,
remove the device, or create an event in the narrow checked Windows event
window, but it also does not validate the runtime's MFG contract.  Following
the safety gate, 4X was not run.  The UI labels 3X/4X as experimental and
unvalidated; no successful output is implied.

## Preview, UI, persistence, and CLI

`Preview Clip` now creates a bounded per-preview directory under
`temp/preview/` containing `source.mp4` and `processed.mp4`.  Source previews
are encoded as H.264/yuv420p with AAC when audio exists and fast-start MP4
layout, then returned to a dedicated **Before / source clip** video component.
The generated MP4 is returned to the paired **After / generated clip**
component.  The four newest preview directories are retained, so Gradio has
time to serve both files rather than receiving a source file deleted by a
`finally` block.

The DLSS-G panel exposes and persists the multiplier, while output files are
tagged `dlssg_2x`, `dlssg_3x`, or `dlssg_4x`.  `tools/dlssg_video.py` accepts
`--multiplier {2,3,4}`.  The 2X compatibility wrapper remains for existing
callers.

## Validation performed

* Native x64 Release build: PASS (pre-existing compiler warnings remain).
* Native protocol self-test: PASS.
* NVOF deterministic direction/conversion test: PASS.
* 2X persistent worker regression: PASS at 256x256, 1280x720, and 1920x1080.
* GPU health after tests: RTX 3070 Ti, driver 610.62; no relevant new narrow-
  window `nvlddmkm`, Display, WHEA, Event 153, Application Error, or WER event.
* Focused DLSS-G/video/UI/persistence tests: 39 passed.

The complete browser-manual playback check, GPU timestamp-query profiling,
natural-video 3X/4X validation, and the GPU-resident motion path remain
outstanding.  The project-owned private resource artifact is updated with this
2X-validated protocol-v4 worker; it does not include either external runtime.
