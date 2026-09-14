# DLSS-G major performance optimization

Date: 2026-09-14  
Hardware: GeForce RTX 3070 Ti, driver 610.62  
Build: native SM86 offline worker, production path

## Result

The normal renderer now has an explicit production/diagnostic split. Production is the default when no artifact directory is requested, and the CLI exposes `--diagnostics` for validation runs.

Production no longer performs generated-frame SHA-256, full-resolution generated-frame MAD scans, stale-output research comparisons, candidate heaps, PNG export, contact sheets, or per-generated manifest retention. It retains protocol/status checks, frame counts, disable/reset/scene-cut handling, cancellation, timing, and output writing. Diagnostic mode retains the previous evidence-producing behavior.

The NumPy MAD implementation also removes the pure-Python byte loop from diagnostic mode. Stage timing is recorded for decode, scene cut, Python diagnostics, native worker processing, encoder writes, and manifest finalization.

## Native NVOF direction experiment

The controlled 256x256 flow test was run with both directions and with `DLSSG_NVOF_DIRECTION=forward`. Both produced the same validated current-to-previous field:

| Check | BOTH | Forward-only |
|---|---:|---:|
| object mean X | -8.1169 | -8.1169 |
| object mean Y | -0.0852 | -0.0852 |
| object median X | -8.0938 | -8.0938 |
| object median Y | -0.1250 | -0.1250 |
| flow valid | 1 | 1 |
| background mean magnitude | 0.3626 | 0.3626 |

Forward-only avoids producing the unused reverse output. It is now the default for production workers; BOTH remains available through the environment variable and is selected by default for diagnostic workers unless explicitly overridden.

## Native 1080p benchmark

Each result uses 20 measured frames after 3 warmup frames, internal NVOF, and the production worker mode.

| Multiplier | Previous median | Forward-only median | Forward-only group rate | Output rate |
|---:|---:|---:|---:|---:|
| 2X | 170.25 ms | 112.85 ms | 8.86 groups/s | 17.72 FPS |
| 3X | 192.85 ms | 132.04 ms | 7.57 groups/s | 22.72 FPS |
| 4X | 212.19 ms | 153.52 ms | 6.51 groups/s | 26.06 FPS |

The forward-only native path meets the requested native targets (<100/<120/<135 ms) only partially: 2X, 3X, and 4X are materially improved, but remain above those aspirational thresholds at this hardware/driver/runtime combination. The benchmark JSON files are intentionally runtime artifacts and remain ignored by Git.

## End-to-end natural 1080p 4X

The same 60-frame 1080p source was rendered in both modes. Audio was disabled for this isolated throughput comparison; audio preservation remains covered by the existing validation path.

| Mode | Wall time | Effective input FPS | Effective output FPS | Python diagnostics |
|---|---:|---:|---:|---:|
| Production | 17.75 s | 3.38 | 13.52 | 0 ms/pair |
| Diagnostic | 32.59 s | 1.84 | 7.36 | 188.95 ms/pair |

The production path is approximately 1.83x faster than diagnostic mode on this clip. Compared with the earlier approximately 0.25 input FPS diagnostic baseline, the production result is approximately 13.5x faster. The large remaining end-to-end cost is native processing plus frame encode/write and decode; the evidence does not support claiming GPU-resident flow conversion, zero-copy color upload, or asynchronous readback yet.

## Verification

- Native flow direction test: PASS for BOTH and forward-only.
- Native worker build: PASS with the NVIDIA Optical Flow D3D12 header mirror and Visual Studio x64 tools.
- Focused Python regression/UI tests: `12 passed, 15 deselected`.
- Full pytest remains blocked by the existing non-admin Windows ACL failure while pytest enumerates stale generated directories under `runtime`/temporary dependency paths. No test was weakened and Administrator mode was not used.

## Follow-up native work

The next performance milestone should target persistent previous-frame NVOF resources, GPU-resident R16G16 conversion, and overlapped queue/readback scheduling. These are deliberately not reported as completed here because they require additional correctness validation against the community runtime and DLSS-G temporal history.
