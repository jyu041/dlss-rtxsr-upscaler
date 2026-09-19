# Managed grid4 worker hardware validation — 2026-09-19

## Result

**PASS** on the project's NVIDIA GeForce RTX 3070 Ti Windows validation machine.

This gate exercised the exact CI-built worker later published as
`dlssg-grid4-worker-v1`; it did not rebuild the worker locally.

## Exact identities

- Worker source/build commit:
  `76702915f5c55423786d6fdd92e69ef1f55bbfa5`
- CI workflow run: `35447075622`
- Worker SHA-256:
  `E097BC87558D6E12ECE1963E67CD7330570BCFBF6C6ED336B10F1EF6DF2A5881`
- Worker size: `613376` bytes
- Candidate ZIP SHA-256:
  `5A6644CC78EFEFB3705C80E7859D53C0E75081AAAE33C676D0DC451BE74B80C9`
- Candidate ZIP size: `209002` bytes
- Release tag: `dlssg-grid4-worker-v1`

The archive contains the project worker, build provenance, NVIDIA RTX SDK
license, and third-party notices. The external SM86 direct-host runtime and
official NVIDIA DLSS-G provider remain separate manifest-managed dependencies.

## Command

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\tools\run_dlssg_grid4_managed_candidate.ps1 `
  -Input "C:\Users\mark\Desktop\trimmed.mp4" `
  -CandidateArchive "C:\Users\mark\Desktop\dlssg-grid4-worker-candidate.zip"
```

The gate verifies the exact archive/worker identities, stages the worker at
`runtime/dlssg/grid4-worker/dlssg_sm86_offline.exe`, runs `--selftest`,
renders a real video through `grid4-gpu-candidate`, and requires
`NVOF_OUTPUT_GRID_SELECTED=4` in the worker log.

## Real-video result

- Input: H.264/yuv420p, 640x480, 442 frames, 29.9993885 FPS,
  14.767868 seconds, AAC audio
- Output: H.264/yuv420p, 640x480, 884 frames, 59.9987771 FPS,
  14.767868 seconds, AAC audio
- Multiplier: 2X
- Generated interpolated frames: 432
- Scene-cut hold frames: 9
- Terminal hold frames: 1
- Interpolation-disabled frame IDs: none
- Device-removal failure results: none
- Worker restart count: 0
- Worker exit code: 0
- Decoder exit code: 0
- Encoder exit code: 0
- Audio and duration preserved: yes

Detected scene cuts were pairs 5, 23, 63, 76, 161, 226, 265, 286, and 341.

## Performance observations

These are observations for this 640x480 test, not universal performance claims:

- Total wall time: 4.7916303 s
- End-to-end output throughput: 184.488 FPS
- Effective input throughput: 92.244 FPS
- Mean worker time per pair: 3.9935 ms
- Mean native total process time: 3.0692 ms
- Mean NVOF upload: 0.3880 ms
- Mean NVOF execute: 0.4079 ms
- Mean flow conversion: 0.0889 ms
- Mean GPU wait: 1.3846 ms
- VRAM before: 753 MiB
- VRAM peak: 1121 MiB

## Acceptance

The run ended with:

```text
DLSSG_GRID4_MANAGED_CANDIDATE_PASS worker_sha256=E097BC87558D6E12ECE1963E67CD7330570BCFBF6C6ED336B10F1EF6DF2A5881 archive_sha256=5A6644CC78EFEFB3705C80E7859D53C0E75081AAAE33C676D0DC451BE74B80C9
```

This establishes that the exact distributable candidate, not merely a
developer-local build, passes the managed real-video application path on the
tested RTX 3070 Ti.

## Scope

C55/grid1 remains the default and fallback. Grid4 remains an explicit
experimental performance profile. This result does not establish compatibility
for every RTX GPU, driver, resolution, codec, source, or runtime combination,
and it is not a claim of perceptual superiority.
