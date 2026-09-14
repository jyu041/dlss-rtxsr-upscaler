# DLSS-G GPU-Resident Pipeline Optimization

Status: partial milestone, 2026-09-14. The worker artifact was synchronized
before native changes. Public source started at `a21cddc8c593f0fcd937fa2100ef48c5201899c1`;
private resources started at `8f441ff533f9eca2c35d8a54548b3424c1daf123`.

## Artifact synchronization

The current public Release x64 worker was rebuilt with the project-owned NVOF
header mirror, passed `--selftest`, and passed the 256x256 forward-only NVOF
test. Its SHA-256 was `7314CC8B5178E5E932F1407700D1E7F088F7217E41832BFBF994AC80F04CF285`.
The same object was copied to the private LFS repository and locked in commit
`6a420b5`, pushed to its `origin/main`. The pre-existing private hash was
`C0EA9BEBEB36A1959F15E21C00714BFB71A6882010DA8368D146418672301F55`.

The final native changes rebuilt and validated a new worker with SHA-256
`8A9C6EFC308D1D6A4F6B6AA192B809CAE32F8D34B53A80BCB9B4E269CF1BA631`.
It is not yet copied to private resources because the code is not being
released as a validated performance milestone.

## Dataflow and implemented changes

Previously, production forward NVOF uploaded both `previous` and `current`
RGBA frames, waited on the upload fence, executed NVOF, waited on the output
fence, read back `R16G16_SINT`, converted S10.5 to FP16 on the CPU, and uploaded
motion to DLSS-G.

The implemented forward-history path is:

```text
seed current -> persistent NVOF previous texture
next current -> one upload -> input fence -> NVOF current->previous
                         -> output readback -> CPU conversion (temporary)
                         -> swap NVOF resource pointers and handles
```

Forward mode now seeds GPU history once and swaps the persistent previous and
current resources/handles after each successful pair. Reset and recreation
invalidate that state. Diagnostic BOTH mode retains the old CPU-reference path.
The production forward path no longer requires `previousColor_`.

Reusable color and NVOF upload heaps are persistently mapped until teardown.
The forward upload submission no longer waits on the CPU; its fence point is
passed to NVOF, which owns the producer/consumer dependency.

## Validation

The 256x256 persistent worker test passed, including reset sequencing and
forward NVOF execution. Self-test and the deterministic forward NVOF flow test
passed with mean X `-8.1169`, mean Y `-0.0852`, median X `-8.0938`, and median
Y `-0.1250`. No device removal was reported.

The recorded forward-only 1080p baseline was 112.85/132.04/153.52 ms per
group for 2X/3X/4X. Fresh runs after GPU history and upload-fence changes were
123.12/146.79/163.69 ms. These runs pass functionally but do not establish a
performance win against the existing baseline; GPU scheduling variance and
the remaining CPU flow path require further investigation.

| 1080p native | Existing baseline | This build |
|---|---:|---:|
| 2X | 112.85 ms | 123.12 ms |
| 3X | 132.04 ms | 146.79 ms |
| 4X | 153.52 ms | 163.69 ms |

## Not yet implemented

GPU S10.5-to-FP16 conversion, GPU-side NVOF output dependency, shared color
upload, MFG output rings, grouped generated readback, D3D12 timestamps, and
async video I/O were not claimed. Consequently the classifications
`DLSSG_GPU_RESIDENT_FLOW_WORKING`, `DLSSG_MFG_READBACK_BATCHED`, and the major
speedup/milestone-complete classifications are not earned.

## Pytest ACL diagnosis

Normal pytest could not start because the local environment lacked pytest.
An elevated read-only run reached collection but failed on missing `cv2` and
`psutil`. The exact project-owned directories `runtime\\pytest-direct2` and
`runtime\\pytest-temp-run` have ACLs granting access only to SYSTEM,
Administrators, and OWNER RIGHTS; the normal `MARK\\mark` token has no entry.
No profile/system ACLs were rewritten.

## Remaining bottleneck and next step

The dominant unremoved path is still NVOF output readback plus CPU S10.5
conversion and motion upload. The next safe milestone should implement and
bit-compare a persistent D3D12 compute conversion resource, then remove the
CPU flow path only after exact synthetic and deterministic NVOF validation.
