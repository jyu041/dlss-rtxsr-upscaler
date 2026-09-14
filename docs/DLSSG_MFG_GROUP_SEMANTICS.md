# DLSS-G MFG Group Semantics

## Scope

This report covers the targeted 3X failure investigation on a GeForce RTX
3070 Ti with driver 610.62. It does not claim 4X support; 4X was not run.

The public SDK contract names `DLSSG.MultiFrameCount` as the number of
intermediate frames and `DLSSG.MultiFrameIndex` as a one-based index through
that group. Therefore the complete generated-index sequences are:

| Requested multiplier | Generated count | Indices per group |
| --- | ---: | --- |
| 2X | 1 | `1` |
| 3X | 2 | `1, 2` |
| 4X | 3 | `1, 2, 3` |

## Control-flow audit

Before this fix, the worker evaluated index 1, waited, and then returned
immediately for an effective reset. A normal group evaluated index 1 with
`Reset=false`, read it back, and only then evaluated indices 2 through the
requested generated count. This made the first normal 3X group dependent on a
reset group that had never completed all of its indices.

The corrected sequences are:

```text
reset group:  for index = 1..generatedCount
              Set MultiFrameCount = generatedCount
              Set MultiFrameIndex = index
              Set Reset = true
              Evaluate -> wait -> readback/record disable
              commit history only after the final index

normal group: for index = 1..generatedCount
              Set MultiFrameCount = generatedCount
              Set MultiFrameIndex = index
              Set Reset = false
              Evaluate -> wait -> readback/validate output
              commit history only after the final valid index
```

Reset readbacks are intentionally discarded. A reset-time disable value is
recorded but does not fail the reset group; normal groups still require
`disable=0`, valid non-endpoint output, and a complete output set.

## Tests

- CPU scheduling tests cover `2X -> (1)`, `3X -> (1,2)`, and `4X -> (1,2,3)`.
- The native Release build completed successfully.
- Persistent synthetic external-motion 3X: PASS, 16 input frames, 28 unique
  generated outputs, two reset groups, ordered generated centroids, no device
  removal.
- Persistent synthetic internal-NVOF 3X: PASS with the same counts and reset
  behavior.
- Natural 1080p 3X: PASS, 60 input frames -> 180 output frames, 118 unique
  generated frames, zero disabled frames, zero stale-output suspects, and no
  device removal. Output was 1920x1080 at exact 90000/1001 fps.

The focused CPU regression set passes (`7 passed`). The repository-wide pytest
run reached the tests but Windows denied access to the pre-existing temporary
pytest directory, so its tmp-path-dependent cases could not complete in this
environment.

## Worker artifact

The rebuilt worker is recorded in the private resources repository and is
paired with the public source commit. The final worker SHA-256 is recorded in
`resources.lock.json`.
