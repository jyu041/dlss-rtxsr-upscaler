# Phase 4A production hardening evidence

Date: 2026-09-15  
Production architecture: frozen; no native worker or GPU-flow changes were made.

## Identity

- Public `main` and `origin/main`: `dbdb0bb299a5f356953c397c8fbfcd64c189aef7`.
- Private resources `main` and `origin/main`: `3fc43317f812f479adbec990c99f2ac20af3d590`.
- Production worker SHA-256: `C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916`.
- Pinned community runtime SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`.
- Private `resources.lock.json` SHA-256: `F1AEF0391B72D2FCC4578E4AFF41B77F450AAF7D978F2905084579DA56286D6F`.
- Worker was not rebuilt or modified.

## Gates

The published native worker passed `--selftest`, `--nvof-flow-test`, and `--resource-pipeline-test`. The NVOF test reported API `0x50`, valid flow, and clean shutdown; the resource test reported all sentinel readbacks matching.

The exact requested candidate suite passed under normal filesystem permissions: `53 passed in 0.28s`. The restricted managed shell still reproduced the known 40-pass/13-setup-error ACL result; no assertion failure was reported in that restricted attempt.

## Harness hardening

`tools/run_dlssg_soak.ps1` now provides resumable per-job artifacts with:

- `START`, periodic `HEARTBEAT`, `PASS`, and failure/timeout output;
- a hard per-job timeout (default 2,400 seconds);
- process-tree termination through `taskkill /T /F` on timeout;
- PASS-artifact skipping, with `-RerunCompleted` as the explicit override;
- retained stdout/stderr and worker diagnostics for successful and failed jobs;
- JSON per-job evidence plus aggregate JSON and Markdown summaries;
- output ffprobe validation, SHA-256 identities, free-space checks, CPU working-set sampling, and inherited VRAM telemetry from the video runner.

The harness smoke job passed in 11.17 seconds and the second invocation skipped the existing PASS artifact without rerunning it. An expected missing-input failure was rejected before worker launch.

## Compatibility evidence recovered or added

The existing `runtime/char_on_*.json` set covers all nine resolution/multiplier combinations: 256x256, 1280x720, and 1920x1080 at 2X, 3X, and 4X. Each is a 20-frame PASS characterization with the expected generated counts and no disabled groups. The existing `runtime/candidate_nvof_gpu.json` is a separate PASS reset protocol run: 80 inputs, 180 unique generated outputs, 20 reset-only frames, and 60 normal frames.

Three non-duplicative short production renders add the missing FPS classes:

| Job | Input FPS | Multiplier | Input/output frames | Generated / terminal | Result |
|---|---:|---:|---:|---:|---|
| `synthetic_256_24fps_2x` | 24 | 2X | 24 / 48 | 23 / 1 | PASS |
| `synthetic_720_2997fps_3x` | 29.97002997 | 3X | 30 / 90 | 58 / 2 | PASS |
| `synthetic_1080_60fps_4x` | 60 | 4X | 60 / 240 | 177 / 3 | PASS |

All three had exact expected output counts, exact rational output rates (48, 90000/1001, and 240 fps), zero scene cuts, zero disabled normal groups, and successful ffprobe validation.

Existing local media was inventoried before adding three openly licensed sources. Prior live-action evidence remains separate and was not reused to collapse these classes.

## Natural-content evidence

All source and output media below remain outside Git under `runtime/phase4a_natural_sources/`. The exercised machine is the RTX 3070 Ti / Windows 10 / driver 610.62 environment. Each render used diagnostics off, forward NVOF, GPU flow, h264_nvenc, normal scene-cut handling, and 4X output.

| Class | Source/provenance and SHA-256 | Production result | Status |
|---|---|---|---|
| Gameplay / HUD / rapid motion | `xonotic_gameplay_15s.webm`, 1024×600, 30 FPS, 15.021 s, VP9/Opus; Wikimedia Commons self-published Xonotic footage, GPLv3; SHA-256 `2C70DA2507917A6BCB773A1450431BFCDEC252FF1CC9639A8426D8FAA83F6C8A` ([source](https://commons.wikimedia.org/wiki/File:Xonotic_0-8-2_gameplay.webm)) | `gameplay_hud.json`: 450 input → 900 output, 448 generated, 1 terminal hold, 60 FPS, 15.014 s video/audio, 1 scene-cut hold, zero disabled groups; output SHA-256 `4CFA508F5AEFCABDFB24D6EC90B2DE61B7CA1D4015BB6AF0BB784BC81974CD84` | PASS |
| Animation / clean edges | `spring_animation_15s.webm`, 2048×858, 24 FPS, 15.021 s, VP9/Opus; Blender Foundation Open Movie, CC BY 4.0; SHA-256 `0B659849D4A3A116035B5ADDD8E57451120D981BF567338B593F5681DD5AA7C1` ([source](https://commons.wikimedia.org/wiki/File:Spring_-_Blender_Open_Movie.webm)) | `animation_clean_edges.json`: 360 input → 1,440 output, 1,077 generated, 3 terminal holds, 96 FPS, 15.014 s video/audio, zero cuts/disabled groups; native 2048×858 retained; output SHA-256 `6AA8738FB1C6AF88F9FF9A88945109DBF9BF3917C93E6BCCFA70C39E1541BFB8` | PASS |
| Low-motion / static | `peccaries_static_15s.webm`, 1920×1080, 10 FPS, 15.000 s, VP8/no audio; fixed-camera collared peccaries, self-published CC BY-SA 3.0; SHA-256 `236955EBF6C48DFAF598B9706A8BABD30CC9AD9BCC12F293D87E95BC826BCAA8` ([source](https://commons.wikimedia.org/wiki/File:Collared_peccaries_as_seen_by_a_fixed_camera_in_Scottsdale,_Arizona.webm)) | `low_motion_static.json`: 150 input → 600 output, 447 generated, 3 terminal holds, 40 FPS, 15.000 s video, no audio, zero cuts/disabled groups; output SHA-256 `6DA88405B3EAEC4748CFDDAFD9C0DAC418EF29515AD299B32C50A1372790A7C3` | PASS |

Independent visual sanity contact sheets are retained under `runtime/phase4a_natural_sources/visual_sanity/`. They show gameplay HUD and motion, animated rendered imagery with high-contrast forms, and a fixed night camera with localized animal motion; no black/corrupt frames, gross ordering failure, or obvious stale-scene leakage was observed. These are bounded correctness checks, not subjective quality scores.

The dedicated `candidate_nvof_gpu.json` reset run provides bounded reset/reseed evidence with 20 resets, no reset output, unique normal generated hashes, and no stale output. The long natural soak independently recorded 888 scene-cut hold frames and zero device removal. No increasing reset-failure rate was observed in either artifact.

## Long natural soak

Evidence: `runtime/phase4a_soak/soak_10m_1080p_4x.json`, `soak-summary.json`, and `soak-summary.md`.

- Local natural source: 1920x1080 H.264/AAC, 600.103033 seconds, 17,779 input frames.
- Exact source rate: 29.626579124662538 fps; exact output rate: 118.50631648495109 fps.
- Multiplier: 4X; output: 71,116 frames at 118.5063 fps.
- Wall time: 1,625.01 seconds; effective input throughput: 10.95 fps.
- Output: 1,766,173,337 bytes; video and audio durations remained aligned at 600.103033 / 600.002993 seconds.
- Calculated output video-minus-audio duration delta: +0.100040 seconds; this is inherited stream-duration padding, while video duration exactly matched the input duration.
- Output codec/pixel format: H.264 / `yuv420p`; color range, BT.709 color space/primaries/transfer metadata were preserved. ffprobe succeeded and reported MP4 with H.264 video plus AAC audio.
- Scene-cut stress: 888 hold frames were recorded; no interpolation-disabled frame IDs were reported.
- Resource stability: one worker process, one NVOF initialization, zero restarts, device removal `0x00000000`.
- VRAM: 860 MiB before, 1,689 MiB peak. Peak sampled process-tree working set: 192.8 MiB.
- The retained short characterization is `runtime/phase4a_soak/memory_3m_1080p_4x_final.json`: 90 samples over 481.60 seconds. The supervised root stayed about 96.4–99.7 MiB after initialization, with one transient 115.1 MiB sample; worker working set remained about 688–720 MiB late, and sampled VRAM remained 1,625–1,628 MiB late. This is **no observed persistent growth in the retained run**, not a universal leak-free claim.
- Worker `ARCH_COUNTERS`: `flow_cpu_readback=0 flow_cpu_conversion=0 motion_cpu_upload=297 gpu_flow_conversion=17482 evaluate_submissions=53337 command_list_submissions=17779 output_copies=53337 disable_copies=53337 readback_slots_used=53337 group_fence_signals=17779 group_waits=17779 input_upload_waits=0 nvof_cpu_waits=297 total_cpu_waits=18076`.
- New short PASS artifacts record separate Python, FFmpeg, and native-worker exit-code fields; the accepted 10-minute artifact remains unchanged and is not rerun.
- The 10-minute job emitted heartbeats continuously and completed under the hard timeout; it was not restarted.

## Release classification

Phase 4A runtime soak result: **PASS for the exercised RTX 3070 Ti / Windows 10 environment**.

Release blocker: reproduce the canonical 53-test suite in a correctly permissioned test environment and attach that clean result. No performance or runtime correctness blocker was found in the completed soak. Compatibility coverage beyond this GPU/OS/runtime identity remains untested and is not claimed by this report.

## Controlled failures, fresh clone, and final gate

Validated harness failures include missing community runtime, missing official runtime directory, missing FFprobe, malformed input, invalid output target, injected encoder exit, exact native-worker termination, and one-second timeout. Failures preserve source and stdout/stderr; timeout writes structured FAIL JSON and aggregate FAIL summary. The deterministic timeout fixture exercised ten parent/child/grandchild cycles; every cycle wrote FAIL evidence and every recorded fixture PID was absent after cleanup. `taskkill /T /F` still reports access denied in this managed shell, but identity-scoped fallback cleanup leaves no fixture process behind.

Compact gate table:

| Gate | Evidence | Status |
|---|---|---|
| Hard timeout, heartbeat, resumability | Harness plus ten tree-fixture cycles; completed PASS artifacts are skipped | PASS |
| Invalid output | `invalid_output_path.json` records the expected bounded FAIL path | PASS |
| Encoder exit | `encoder_exit_17_final2.json`; injected fake exits 17 and the diagnostic names the code | PASS |
| Worker exit | `worker_exit_exact_child.json`; exact worker PID was terminated and pipe closure retained | PASS |
| Memory characterization | `memory_3m_1080p_4x_final.json`, 90 samples / 481.60 s | PASS, short-scope only |
| Natural content classes | `gameplay_hud.json`, `animation_clean_edges.json`, `low_motion_static.json` plus visual sanity sheets | PASS |
| Canonical pytest | Exact requested candidate: `53 passed in 0.28s` | PASS |
| Native self-test | Published worker `--selftest` exit 0 | PASS |

A clean local clone at `6f1512a1c61fac00799e523ff758782dde4f4bc6` passed `git diff --check`, worker self-test after manual private-resource provisioning, and one short 1080p/4X production render. The first clone render correctly failed when FFmpeg was absent from PATH; supplying the documented FFmpeg PATH produced PASS. No development-native output directory or SDK headers were required.

Final gate status: **BACKEND HARDENING BASELINE ESTABLISHED**. All Phase 4A gates pass on the exercised RTX 3070 Ti / Windows 10 / driver 610.62 environment. This does not claim universal compatibility.

## Findings

| Priority | Finding | Status |
|---|---|---|
| P0 | Data loss, security issue, or system instability | None observed |
| P1 | Timeout cleanup initially left an externally spawned worker after `taskkill` returned access denied | Closed by ten deterministic parent/child/grandchild cycles with zero recorded PID survivors |
| P2 | Natural-content coverage is limited to the three recorded licensed sources and exercised machine | Scope limitation; no Phase 4A blocker |
| P2 | Invalid output target, encoder unexpected exit, and worker unexpected exit | Closed with retained expected-failure artifacts |
| P2 | Per-timepoint memory slope/plateau samples were not retained by the accepted soak | Closed for the short characterization; long-soak time-series was intentionally not rerun |
| P3 | Independent exit-code telemetry | Closed for new short PASS artifacts; accepted long artifact remains historical |
