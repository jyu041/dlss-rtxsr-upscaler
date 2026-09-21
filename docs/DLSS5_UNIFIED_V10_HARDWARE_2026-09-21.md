# Unified DLSS 5 v10 Pipeline Hardware Evidence — 2026-09-21

This record covers the unified DLSS 5 migration introduced by PR #40. The
hardware run exercised the preferred v10 application renderer at commit
`ed8df012510aa9926437a1afde3573b2c3ecc34d`, including the
application-level reduced-working-resolution, residual-recomposition, temporal
stabilization, and multi-pass interaction cases that previously existed only in
the v3-side pipeline.

## Scope

Tested machine:

- GPU: NVIDIA GeForce RTX 3070 Ti
- source: owned 640x480 / ~30 fps clip
- duration per case: 2 seconds / 60 compared frames
- application pixel format: SDR RGBA8
- preferred runtime: isolated Visual Enhancer v10 Feature-18 application path
- output scale: 1.0x
- recomposition policy: Auto, resolving to CUDA for reduced-resolution cases

Before the matrix, the preferred backend reported `EXPERIMENTAL READY` with a
clean preflight. The matrix completed with `DLSS5_V10_QUALITY_MATRIX_PASS`.

## Results

| Case | Working resolution | Processing FPS | Effect MAE | Residual flicker MAE | Recompose |
| --- | ---: | ---: | ---: | ---: | --- |
| baseline-current | 640x480 / 100% | 23.28 | 3.871 | 1.076 | native |
| working-0p75 | 480x360 / 75% | 25.83 | 3.935 | 1.100 | CUDA |
| working-0p666 | 426x320 / 66.7% | 27.55 | 4.034 | 1.114 | CUDA |
| working-0p75-temporal-0p5 | 480x360 / 75% | 16.83 | 3.894 | 1.006 | CUDA |
| passes-4 | 640x480 / 100% | 9.93 | 11.924 | 1.677 | native |
| passes-4-working-0p75 | 480x360 / 75% | 11.90 | 12.082 | 1.705 | CUDA |

All listed cases retained three scene resets.

Relative to native-resolution one-pass v10:

- 75% working resolution improved processing throughput by about 10.9%;
- 66.7% working resolution improved processing throughput by about 18.3%;
- the 75% case changed effect MAE by about +1.6% and residual-flicker MAE by
  about +2.2%;
- the 66.7% case changed effect MAE by about +4.2% and residual-flicker MAE by
  about +3.6%.

The four-pass / 75% interaction case improved processing throughput by about
19.9% relative to native-resolution four-pass processing while its effect and
flicker metrics remained close to the native-resolution four-pass case.

The application-level temporal stabilizer reduced residual-flicker MAE from
1.100 at 75% without stabilization to 1.006 at 75% / strength 0.5, an
approximately 8.5% reduction. The current CPU optical-flow/composition
implementation is expensive, reducing processing throughput by about 34.8%
relative to the otherwise-equivalent 75% case. This confirms functionality but
also identifies temporal stabilization as a future GPU-optimization target.

## Interpretation

The run establishes that the preferred v10 application path can execute the
shared reduced-resolution/recomposition pipeline on the tested RTX 3070 Ti and
that CUDA recomposition is selected successfully for the reduced-resolution
cases. The measured quality indicators remain close to native-resolution v10
for 75% and 66.7% on this source while providing measurable steady-state
throughput gains.

These metrics are diagnostic, not a perceptual ranking. The benchmark review
videos still require a human spot check before PR #40 is promoted from draft.
The H.264 review encode also means the quality metrics should not be treated as
lossless reference measurements.

The result does not widen the validated native-input boundary beyond SDR RGBA8,
1.0x output, and the existing 1920x1080-equivalent v10 application scope. It
also does not establish cross-GPU compatibility or official RTX 30-series DLSS
5 support.
