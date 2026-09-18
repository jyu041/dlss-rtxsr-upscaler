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
- global per-channel RGB SSIM averaged across the three channels.

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
