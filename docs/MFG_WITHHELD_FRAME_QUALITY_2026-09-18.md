# MFG Withheld-Frame Quality Harness — 2026-09-18

This research branch adds a renderer-independent quality harness for DLSS-G /
MFG validation. It performs no GPU work by itself.

## Method

For multiplier `M`, start from a higher-frame-rate ground-truth sequence and
retain only every M-th frame as an anchor stream. The real frames between each
pair of anchors are withheld.

Example for 4X:

```text
source:   F0 F1 F2 F3 F4 F5 F6 F7 F8 ...
anchors:  F0          F4          F8 ...
hidden:      F1 F2 F3    F5 F6 F7
```

The MFG backend receives the anchor stream. Its generated indices 1..M-1 are
then compared against the corresponding real hidden frames.

This is a materially stronger quality test than comparing a generated frame
only with its neighboring anchors because the hidden real frame provides a
ground-truth target at the intended temporal position.

## Implemented metrics

`src/core/mfg_quality.py` provides deterministic RGB-only metrics:

- mean absolute error (MAE);
- root mean square error (RMSE);
- PSNR;
- global per-channel RGB SSIM averaged across the three channels;
- reference-edge MAE over pixels whose Rec.709 luma has a one-pixel
  horizontal/vertical gradient of at least 20 code values.

Alpha is intentionally ignored.

Identical frames report `psnr_db: null` rather than JSON-incompatible
infinity, while `identical: true` and `ssim_rgb: 1.0` preserve the exact
result.

The SSIM implementation is deliberately dependency-light and global rather
than windowed/skimage SSIM. Reports identify the exact metric contract so
results are not confused with a different SSIM implementation.

## Group planning

`withheld_groups(frame_count, multiplier)` deterministically maps:

- left anchor index;
- right anchor index;
- hidden source indices;
- generated index 1..M-1 correspondence.

2X, 3X, and 4X are supported.

## Offline scorer

`tools/score_mfg_withheld.py` consumes an explicit JSON manifest and performs
no DLSS-G execution.

Example:

```json
{
  "multiplier": 4,
  "samples": [
    {
      "group": 0,
      "generated_index": 1,
      "reference": "references/g000_i1.png",
      "generated": "generated/g000_i1.png"
    }
  ]
}
```

Run:

```powershell
python tools\score_mfg_withheld.py runtime\quality\manifest.json --output runtime\quality\report.json
```

The report retains per-sample evidence and aggregates results both overall and
by generated index. Keeping generated indices separate is important for 3X/4X:
index 1 may have materially different quality or performance from later
indices.

## What this does not establish

A good PSNR/SSIM result does not prove perceptual quality. It also does not
directly capture:

- temporal flicker;
- object hallucination;
- occlusion/disocclusion failure;
- text/UI deformation;
- dissolve or hard-cut behavior;
- face/hand perceptual quality.

Those need targeted clips and temporal/perceptual checks later. The current
harness is the deterministic first quality baseline.

## Next capture step

After the instrumented worker passes its bounded 256x256 matrix, capture a
small high-FPS source set containing:

1. smooth translation;
2. foreground occlusion/disocclusion;
3. thin high-contrast detail;
4. camera motion;
5. a hard cut;
6. a dissolve.

Generate 2X/3X/4X anchor-stream outputs, construct explicit scorer manifests,
and retain the metric reports alongside timing evidence.

## Automated grid 1 versus grid 4 capture

`tools/capture_mfg_grid_quality_ab.py` now automates the first quality gate for
the coarse-grid candidate.

The tool:

- accepts a user-supplied higher-frame-rate source clip;
- is currently bounded to 640x480, 1280x720, or 1920x1080;
- supports 2X and 4X only for this comparison;
- retains every M-th source frame as the anchor stream;
- uses the real frames between anchors as withheld ground truth;
- runs the same instrumented worker twice, once with NVOF grid 1 and once with grid 4;
- writes one shared immutable reference set plus separate generated sets;
- scores both runs with the existing RGB MAE/RMSE/PSNR/global-SSIM contract;
- emits a combined `grid-ab-quality-report.json` with grid4-minus-grid1 metric deltas.

Runtime safety gates remain in force:

- the worker must live under `bin-instrumented`;
- the production C55 hash is explicitly rejected;
- the legacy community runtime and NVIDIA provider hashes must match the pinned validated identities;
- grid environment variables are restored after each run.

Example:

```powershell
python tools\capture_mfg_grid_quality_ab.py `
  --input C:\path\to\high-fps-test.mp4 `
  --multiplier 2 `
  --groups 8
```

The base output tree defaults to `runtime/quality/mfg-grid-ab`. Each run is
automatically namespaced as:

`<source-stem>-<source-sha12>/<multiplier>x/start-<frame>/`

so different multipliers and different source segments cannot silently overwrite
each other. The combined report also records the selected start/end frame, source FPS,
derived anchor FPS, and source-frame/anchor-frame intervals. A 29.97-fps source
used for a 2X withheld-frame comparison therefore produces an approximately
14.985-fps anchor stream. That remains useful as a grid-1 versus grid-4
coarse-temporal stress test, but it must not be presented as a direct proxy for
a 60-fps source reduced to 30-fps anchors.

No automatic pass/fail quality threshold is encoded yet. A metric delta is
evidence, not a promotion rule. Temporal flicker, motion boundaries,
occlusion/disocclusion, text/UI, thin detail, scene cuts, faces and hands still
require targeted perceptual review.


### Pairing contract

Grid 1 and grid 4 reports must contain exactly the same
`(group, generated_index)` sample keys. The combined report fails closed if
they differ. For each paired frame, the report retains grid4-minus-grid1 deltas
for MAE, RMSE, PSNR, SSIM, and edge MAE.

Metric direction is explicit:

- lower is better: MAE, RMSE, edge MAE;
- higher is better: PSNR, SSIM.

No aggregate quality threshold is currently encoded. This avoids turning one
small or content-specific capture into an unsupported promotion rule.

## Temporal consistency and review artifacts

The quality A/B harness now evaluates temporal evolution in addition to
per-frame spatial metrics.

For each consecutive source-frame transition, it compares the real RGB temporal
derivative with the reconstructed candidate sequence's temporal derivative.
Anchors use the original source frames; withheld positions use the generated
grid-1 or grid-4 frame. The report includes:

- mean temporal-delta MAE;
- p95 temporal-delta MAE;
- maximum temporal-delta MAE;
- mean temporal-delta RMSE;
- per-transition evidence;
- grid4-minus-grid1 mean temporal-delta MAE.

This is still a deterministic signal rather than a complete flicker metric, but
it detects cases where individual generated frames are spatially reasonable
while their frame-to-frame evolution is less faithful.

The combined report also ranks the worst grid-4 spatial regressions, prioritizing
reference-edge MAE, then SSIM and global MAE. For each ranked sample the harness
writes a review triptych with:

1. withheld real reference;
2. grid-1 output;
3. grid-4 output.

These review images are written under the evidence run's `review/` directory.

## One-command local quality gate

The PowerShell wrapper:

`tools/run_mfg_grid_quality_ab.ps1`

first rebuilds and GPU-free self-tests the isolated instrumented worker, then
runs the real-clip grid quality A/B with the pinned legacy/runtime identities.

Example:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_mfg_grid_quality_ab.ps1 `
  -Input "C:\path\to\high-fps-test.mp4" `
  -Multiplier 2 `
  -Groups 8 `
  -StartFrame 0
```

The wrapper performs no production-profile promotion and invokes no practical
timing matrix. It exists only to make the real quality gate reproducible.

Use `-StartFrame` (or Python `--start-frame`) to sample multiple distinct
motion segments from the same source without replacing prior evidence. This
is preferable to relying only on the first seconds of a clip, which may contain
logos, fades, or static lead-in.
