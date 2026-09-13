# Natural-Video DLSS-G 2X Validation

## A. Baseline

Validation started from `main` commit
`53370b46d672e5746a65764791e6c4aa529c2fdf`, with the persistent-worker
milestone at `2059e6978334b5f139f79411db736a641582e0d7` and the offline proof at
`9ef7f8c81cec5e1780f7fb8605dd5ccaeefb14bc`.

The test system was an NVIDIA GeForce RTX 3070 Ti on driver 610.62. The
rebuilt worker SHA-256 was
`603CFB2D14C4EC923747183FF9808EB05CB8ECF830729359455589DF4A641B7C`.
Runtime provenance was unchanged:

- external community `version.dll`:
  `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`;
- system `nvofapi64.dll` 32.0.16.1062:
  `9A25A1E63B2F16FB4F8349A7CA3B39976CCD0F7140B7C8C8E4981BCB81491C51`;
- matched `nvngx_dlssg.dll` 310.9.1.0:
  `FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82`.

No community, NVIDIA, generated-video, diagnostic-image, or runtime-log binary
is tracked by Git.

## B. Investigation tracks

No sub-agent execution facility was available in this session, so the requested
read-only investigations were conducted as separate main-agent review tracks.

### Visual-quality rubric

The review covered moving silhouettes, hair and hands, disocclusion, camera and
subject motion, faces, the window-lattice thin/repeated pattern, source
cross-dissolves, scene cuts, temporal midpoint placement, and stale-frame
flicker. The rubric was adopted for automatic difficult-transition selection
and manual triplet/contact-sheet review.

### NVOF/DLSS-G contract audit

The working direction and scale remain unchanged: previous A is the NVOF input,
current B is the reference, backward B-to-A flow is consumed, S10.5 components
are divided by 32, packed as R16G16 FP16, and used with scale `(1/width,
1/height)`. Frame IDs remain monotonic. CREATE and scene-cut reset invalidate
history; the next frame performs a reset Evaluate. No evidence justified
changing those established invariants.

### Video timing/encoding audit

The audit found and fixed two concrete output-contract defects:

1. `-shortest` allowed a 15.000-second audio stream to truncate a
   15.015-second video stream and drop the intended terminal hold.
2. the Matroska intermediate quantized 60000/1001 timestamps to milliseconds,
   producing an advertised 59.944 fps rather than exact 60000/1001.

The corrected path uses the exact source rate rational, an MP4 video
intermediate with an explicit track timescale, and remuxes audio without
`-shortest`. H.264/HEVC VUI metadata is written explicitly because container
metadata alone did not preserve primaries/transfer through raw-RGBA NVENC.

## C. Input clip

The input was a user-designated Desktop video. A 15-second excerpt was copied
to ignored runtime storage; the original user file was not modified. The path
category is therefore **user-designated local media**, not a repository fixture.

- codec/pixel format: H.264, `yuv420p`;
- dimensions: 640x480;
- rate: 30000/1001 (29.97002997 fps);
- decoded frames: 450;
- container/video duration: 15.015 seconds;
- audio: AAC, 15.000 seconds;
- color identity: limited-range BT.709 primaries, transfer and matrix;
- HDR: no.

Input SHA-256 in ignored runtime storage was
`6B1912DF86F3FA1836B0534B0385996D96725BA987DA754AD92EE0D188D8D367`.

## D. Output and timeline

The production backend produced:

- dimensions: 640x480;
- rate: exact 60000/1001 (59.94005994 fps);
- encoded/decoded frames: 900/900;
- video duration: 15.015 seconds;
- audio: original AAC stream preserved, 15.000 seconds;
- color identity: limited-range BT.709 preserved in the elementary stream;
- output SHA-256:
  `FFE640FF78DEC709011174F143846B90D930A558513913C404096C64CDAC4266`.

The terminal policy is exact 2X CFR: for N input frames, emit N real frames,
N-1 midpoint slots, and one final real-frame hold, for 2N output frames. Six
hard-cut midpoint slots were source-frame holds rather than generated frames.
Thus this run contained 443 unique generated midpoint frames, six scene-cut
holds, and one terminal hold.

Decoded validation independently checked every temporal slot, exact frame
count/rate/duration, the scene-cut holds, terminal hold, audio presence and
duration, and color metadata. Result: PASS. Normal encode loss accounts for a
mean real-slot MAD of 1.066 and terminal-hold MAD of 1.055; those are not
temporal mismatches.

## E. Motion diagnostics

Protocol v3 returns per-pair NVOF statistics from the native worker without a
second flow readback. Across the 443 interpolated natural pairs, means were:

- flow X/Y: `(0.6323, -0.0423)` pixels;
- median X/Y: `(0.4875, -0.1661)` pixels;
- 95th-percentile magnitude: 9.7226 pixels;
- maximum magnitude: 39.6269 pixels (mean of pair maxima);
- magnitude standard deviation: 3.7263 pixels;
- near-zero vectors: 21.4013%;
- unusually-large vectors: 0.0203%.

The deterministic 256x256 direction regression remained valid after rebuild:
moving-object mean `(-8.1057, -0.0698)`, median `(-8.1250, -0.0938)`, and
background mean magnitude `0.3566`. This rules out a systemic sign or pixel
scale regression.

Eight difficult transitions were selected by a combined flow-p95,
flow-variance and real-pair-MAD score: pairs 93, 365, 440, 441, 94, 435, 80 and
81. Their previous/generated/current PNGs and contact sheet are stored only in
the ignored runtime diagnostics directory.

## F. Visual QA

- **Temporal placement:** coherent translations and face motion place the
  generated image between adjacent real frames; no systematic endpoint bias
  was visible.
- **Faces/hands:** close face and mouth motion remained recognizable and
  temporally plausible, with mild softness at rapidly changing features.
- **Moving edges/disocclusion:** fast hair, arms and body silhouettes show the
  most blur/warping. This is consistent with optical-flow ambiguity and the
  flat depth field at foreground/background boundaries.
- **Thin/repeated detail:** the window lattice remained structurally stable at
  contact-sheet scale. Source softness limits stronger conclusions.
- **Cross-dissolves:** several source frames already contain two blended shots.
  Their generated midpoints inherit or intensify double exposure. They are not
  hard cuts and are intentionally not classified by the current one-pair hard
  cut detector. Dissolve-aware temporal transition handling remains follow-up
  work.
- **Hard cuts:** six high-MAD/high-histogram-distance cuts were detected at
  input pair IDs 66, 187, 260, 319, 364 and 434. Each caused
  `RESET_HISTORY`, emitted a previous-source hold, and prevented cross-shot
  interpolation.
- **Flicker/stale output:** no stale or repeated generated hash was observed;
  selected-frame review found no global oscillation. Full perceptual flicker
  scoring was not attempted.

The output is useful and the contract is correct, but constant depth remains a
visible quality limitation at occlusions and parallax boundaries. The sample
does not isolate enough depth ground truth to justify coupling a monocular
model into the backend. `EXTERNAL_R32_FLOAT` depth remains the preferred next
experimental API rather than a mandatory model.

## G. Generated-frame integrity

- successful generated outputs: 443;
- unique generated SHA-256 values: 443;
- generated equals previous endpoint: 0;
- generated equals current endpoint: 0;
- stale generated-output suspects: 0;
- `OUTPUT_DISABLE != 0`: 0;
- worker restarts: 0;
- D3D12 device removal result: only `0x00000000`.

The representative difficult pairs had high flow where expected. For example,
pair 93 (a source cross-dissolve) had p95 magnitude 152.99 pixels and 4.74%
unusually-large vectors; pair 440 (fast hair/body motion) had p95 40.40 pixels.
This diagnostic separation helps distinguish transition/occlusion failures
from a global flow-direction defect.

## H. Performance

### 640x480, 450-frame natural run

These are the timings from the full validation run before percentile diagnostic
sampling was bounded. Generated pixels and flow means/maxima were unaffected by
the subsequent diagnostics-only optimization.

- decode: 0.913 ms/input frame;
- NVOF upload: 3.756 ms/pair;
- NVOF execute: 27.854 ms/pair;
- CPU flow conversion: 7.481 ms/pair;
- DLSS-G/input upload: 44.888 ms/pair;
- Evaluate CPU call: 0.244 ms/pair;
- GPU wait: 16.800 ms/pair;
- output readback: 1.529 ms/pair;
- total native process request: 63.704 ms/pair;
- encode pipe write: 0.444 ms/output frame;
- wall time: 142.856 seconds;
- effective input/output throughput: 3.150/6.300 fps;
- peak dedicated VRAM observed: 1,149 MiB.

The dominant measured stages are synchronous DLSS-G upload, NVOF execution,
and GPU wait. Decode and encoder pipe writes are not the bottleneck. The design
still deliberately favors correctness over GPU-resident flow conversion and
multiple in-flight work.

### 1920x1080 bounded stability run

A two-second excerpt of the same user-designated clip was aspect-preservingly
scaled to 1440x1080 and pillarboxed to 1920x1080. It produced 120/120 frames
from 60 inputs: 59 unique midpoints and one terminal hold, exact 60000/1001
rate, exact 2.002-second video duration, preserved 2.000-second audio, no
disabled/stale/endpoint-duplicate output, no restart, and no device removal.

- NVOF execute: 145.665 ms/pair;
- CPU flow conversion/statistics: 15.120 ms/pair;
- DLSS-G/input upload: 190.288 ms/pair;
- GPU wait: 24.121 ms/pair;
- total native request: 220.981 ms/pair;
- wall time: 107.292 seconds;
- peak dedicated VRAM: 1,583 MiB.

Bounding median/p95 samples to 65,536 points reduced 1080p conversion/statistics
time from 46.265 to 15.120 ms while retaining exact full-frame means, maxima,
variance and threshold counts. The synthetic direction regression was rerun
after this optimization and remained unchanged.

This proves 1080p stability and resource recreation, not native-source 1080p
perceptual quality.

## I. Gradio path

The project-pinned environment reported Gradio 6.16.0. The actual
`render_video` callback was invoked with **DLSS Frame Generation 2X**, NVIDIA
Optical Flow, constant 0.5 depth, and the configured external runtime paths on
a two-second natural excerpt.

Result: 60 inputs to 120 outputs at exact 2X FPS and duration, audio and BT.709
preserved, completion returned the expected video path, and zero
`.dlssg-video.*` intermediates remained. This confirms backend selection,
runtime-path validation, progress/job completion, result publication, and
normal temporary-file cleanup. Preview-source cleanup was also moved into a
`finally` block so failed/cancelled previews do not leak their temporary input.

## J. GPU health

Natural-run snapshots were 39 C / 736 MiB before and 40 C / 744 MiB after.
The 1080p run peaked at 1,590 MiB and ended at 42 C / 760 MiB. The GPU remained
responsive on driver 610.62.

- D3D12 device removal: none;
- new `nvlddmkm` Event 153: **NO**;
- relevant System events (`nvlddmkm`, Display, WHEA): 0;
- Application Error events: 0;
- one informational WER `RADAR_PRE_LEAK_64` event named `explorer.exe` occurred
  in the broad collection window and was unrelated to the worker;
- one informational WER `RADAR_PRE_LEAK_64` event named
  `dlssg_sm86_offline.exe` occurred at normal worker exit. There was no
  exception or Application Error. This is consistent with the deliberately
  process-owned NGX runtime and documented no-`NGX_Shutdown1` exit policy used
  to avoid the known shutdown hang. It does not leak across worker processes,
  but clean NGX teardown remains explicit technical debt.

## K. Tests

- x64 MSVC Release `/W4` build: PASS;
- native `--selftest`: PASS;
- NVOF synthetic direction/conversion test: PASS;
- focused DLSS-G tests: PASS;
- full Python suite: 69 passed, 2 skipped;
- decoded 640x480 natural-video validation: PASS;
- decoded 1920x1080 stability validation: PASS;
- Gradio 6.16 render callback: PASS;
- `git diff --check`: PASS.

The native build retains pre-existing non-fatal warnings for unused probe
helpers, one deprecated `sprintf`, one unused parameter, and compiler-reported
unreachable probe code. No new material warning was introduced by this work.

## L. Primary result

`REAL_VIDEO_DLSSG_2X_BACKEND_VALIDATED_WITH_KNOWN_DEPTH_LIMITATION`

The natural clip completes with correct generation, ordering, exact timing,
audio and color identity; no systemic motion sign/scale/timeline issue exists.
The dominant visible weaknesses are fast disocclusion/silhouette handling and
source cross-dissolves, with flat depth remaining the clearest backend quality
limitation.

## M. Remaining quality issues

1. add optional caller-supplied `EXTERNAL_R32_FLOAT` depth without making a
   monocular model mandatory;
2. add dissolve-aware multi-frame transition detection separately from the
   conservative hard-cut detector;
3. move NVOF S10.5-to-FP16 conversion and, where possible, decoded input upload
   fully onto the GPU;
4. reduce synchronous upload/wait costs before pursuing higher resolutions;
5. validate visual quality with native-source 1080p material containing strong
   parallax, thin structures, and occlusions;
6. keep 3X/4X out of scope until 2X quality and throughput are robust.
7. investigate the normal-exit `RADAR_PRE_LEAK_64` diagnostic without invoking
   the known-hanging NGX shutdown path.

## N. Commits and push

- starting remote/main: `53370b46d672e5746a65764791e6c4aa529c2fdf`;
- quality/hardening implementation:
  `fea7f3c1c1e373e22ce1692a0389172848592536`;
- validation-report commit: the commit containing this document; its exact SHA
  is recorded in the final task handoff;
- generated media, contact sheets, flow diagnostics, worker logs, native build
  products, external community runtime, and NVIDIA runtime DLLs remain ignored
  or external.

The push result and verified final `origin/main` are recorded in the final task
handoff because a commit cannot contain its own SHA or a future remote state.
