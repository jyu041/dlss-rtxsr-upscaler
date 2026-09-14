# DLSS-G 4X and Performance Optimization

## A. Starting commits

- Public: `2190648bb30c92f5849646857c17806d0ffb257e`
- Private resources: `032f44356c0a30b6963c1fcfd80dff673a199eff`
- GPU: GeForce RTX 3070 Ti, driver 610.62
- Community runtime: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`, SHA-256
  `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`

## B. 4X contract and validation

4X uses `MultiFrameCount=3` and indices 1, 2, 3. The reset group evaluates
all three with `Reset=true`; the normal group evaluates all three with
`Reset=false`. One real frame ID is used for all three evaluations, and
history is completed only after the final group index.

The RTX 3070 Ti passed both deterministic external-motion and internal-NVOF
4X persistent tests: 16 input frames, 42 unique generated outputs, complete
reset and normal groups, ordered moving-object centroids, no disabled normal
outputs, no stale outputs, and no device removal.

The natural 1920x1080 clip also passed at 4X: 60 input frames produced 240
output frames at exact 120000/1001 FPS, with 177 unique generated frames and
three terminal holds. Audio, duration, resolution, and BT.709/SDR metadata
were preserved; no interpolation-disabled frames or scene-cut holds occurred
in this clip.

Classification: `DLSSG_4X_MFG_WORKING`.

## C. Performance architecture

Before optimization, one internal-NVOF group followed this broad path:

```text
CPU RGBA
  ├─ upload/wait → NVOF previous texture
  ├─ upload/wait → NVOF current texture
  ├─ NVOF → R16G16_SINT GPU flow
  ├─ readback/wait → CPU flow
  ├─ CPU S10.5 / 32 conversion → R16G16_FLOAT CPU motion
  ├─ upload/wait → DLSS-G motion texture
  └─ upload/wait → DLSS-G color texture → sequential Evaluate/readback per index
```

This milestone makes two safe host-side changes. NVOF previous/current input
copies are recorded in one submission, and production mode omits the
diagnostic sentinel prefill before each generated output. NVOF remains on its
existing queue and the worker still permits only one real-frame group in
flight.

The resulting production path is:

```text
CPU RGBA → batched real-frame preparation → NVOF → existing CPU flow conversion
                                      └──→ DLSS-G color/motion → sequential MFG group
production output → required CPU readback
diagnostic output → sentinel/readback/hash/statistics validation
```

The NVOF D3D12 API already uses caller-owned registered D3D12 resources for
its previous/current inputs and forward/backward outputs. The current public
wrapper does not expose a safe consumer-facing GPU flow resource or conversion
queue contract, so the full CPU flow round-trip was not removed speculatively.
That remains the primary next optimization target. Duplicate CPU color upload
elimination is likewise not claimed.

## D. Benchmark evidence

Each benchmark used three warm-up groups and 20 measured groups. Values are
median native `PROCESS` time; files are preserved under `runtime/benchmarks/`.

| Resolution | 2X | 3X | 4X |
| --- | ---: | ---: | ---: |
| 256x256 | 12.65 ms | 18.92 ms | 13.75 ms |
| 1280x720 | 89.13 ms | 105.38 ms | 121.62 ms |
| 1920x1080 | 170.25 ms | 192.85 ms | 212.19 ms |

1080p baseline versus optimized production:

| Multiplier | Baseline | Optimized | Speedup |
| --- | ---: | ---: | ---: |
| 2X | 219.84 ms | 170.25 ms | 1.29X |
| 3X | 265.30 ms | 192.85 ms | 1.38X |
| 4X | 291.40 ms | 212.19 ms | 1.37X |

Optimized 1080p capacity is 5.87, 5.19, and 4.71 real groups/s, or 11.75,
15.56, and 18.85 output frames/s for 2X, 3X, and 4X respectively. End-to-end
natural 4X throughput on the tested 60-frame clip was 0.25 input frames/s and
1.00 output frames/s, dominated by CPU decode/encode plus native processing.

Stage evidence explains why the requested 2X latency improvement was not
reached: after the changes, NVOF execution/wait remained about 90 ms at
1080p, while CPU flow conversion remained about 10.4 ms. The optimization is
material but `DLSSG_1080P_PERFORMANCE_SIGNIFICANTLY_IMPROVED` is not claimed at
the requested 2X threshold.

## E. GPU health and regression status

Before 4X: 801 MiB / 8192 MiB VRAM, 36°C, P8, 15.03 W. After 4X: 802 MiB,
37°C, P8, 14.87 W. No new `nvlddmkm`, Display, WHEA, Event 153, Application
Error, or WER events appeared in the experiment intervals.

Native Release `/W4` build, self-test, NVOF direction test, 2X/3X/4X timing
tests, settings/timeline tests, and focused MFG scheduling/history tests pass.
The repository-wide pytest run is currently blocked by the host’s inherited
Windows ACL denying pytest temporary-directory enumeration; redirecting
TEMP/TMP and `--basetemp` to fresh project-local and writable Codex paths did
not change that ACL behavior. No tests were weakened and the issue is recorded
instead of being bypassed with Administrator execution.

## F. UI and remaining work

The UI now reports `DLSS-G 2X/3X/4X` as validated, while the multiplier remains
persistent and the CLI uses the same renderer. The remaining high-value work
is a contract-backed GPU flow conversion/resource handoff, followed by
re-measurement. Until that is implemented and measured, the CPU flow
round-trip and duplicate color upload remain explicit limitations.
