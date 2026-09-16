# Phase 5 DLSS5 v9 static candidate audit

Audit date: 2026-09-16

This is a static, non-execution audit of the public `v9.0` release from
[Merserk/dlss5-visual-enhancer](https://github.com/Merserk/dlss5-visual-enhancer).
The source repository is MIT-licensed, but that does not make the included
NVIDIA or other third-party binaries MIT-licensed.

## Release identity

| Field | Value |
|---|---|
| Release | `v9.0` |
| Release asset | `DLSS.5.Visual.Enhancer.v9.0.zip` |
| Asset size | `509001461` bytes |
| Asset SHA-256 | `F531426E0B6C935C2ECC6299121F910E3921FC6CBD589C9A3B95A78A1D589D71` |
| Asset URL | `https://github.com/Merserk/dlss5-visual-enhancer/releases/download/v9.0/DLSS.5.Visual.Enhancer.v9.0.zip` |
| Source commit observed | `c95c050ead79b9409f140e0b2a66a7b91cffb258` |

## Relevant binary inventory

Hashes below are for files inside the release archive, not files committed to
this repository.

| Relative path | Bytes | SHA-256 | Authenticode |
|---|---:|---|---|
| `bin/runtime/dlssnr/nvngx_dlssnr.dll` | 165830144 | `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927` | NotSigned |
| `bin/runtime/dlssnr/neuroframe_engine.dll` | 570880 | `2BDC5BFD59906DF7CB6DF98F78339D68F741B11256A26927A4C107425E7F46D4` | NotSigned |
| `bin/runtime/dlssnr/neuroframe_caller.dll` | 104960 | `58E2850F96FC1B81A9154E059E3F3A42239440280C79E1CE41F6142CA9F1BAD4` | NotSigned |
| `bin/runtime/dlssg/neuroframe_engine.dll` | 221184 | `AAC4156464CB1A7DFBF1D335C7B2BFF58F1A98486E04D5B875A843721656BE10` | NotSigned |
| `bin/runtime/dlssg/nvngx_dlssg.dll` | 7460976 | `FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82` | Valid |
| `bin/runtime/rtx_video/nvngx_vsr.dll` | 19140144 | `C3D88EEA5FF7A548EDEFA66414CF6E77464D0947277C904F324DD23ABF58A1ED` | Valid |
| `bin/runtime/rtx_video/nvngx_truehdr.dll` | 3955752 | `9A80575F247190C05FE80EAC0C4BAA1D0D4D932348F26808310B5EC4BF9EEB4B` | Valid |
| `bin/runtime/rtx_video/neuroframe_engine.dll` | 2086912 | `417D905A766E5E62C4CA37F6891FD5A9687F6051865EE97F0D3560828AE2314C` | NotSigned |

The archive also contains an embedded `python-3.13.15-embed-amd64` tree,
portable FFmpeg/FFprobe, `mpv`, `yt-dlp`, project code, and multiple license
files. The embedded launcher demonstrates a viable portable-Python layout, but
its dependency environment and application architecture are not drop-in
compatible with this project.

## Licensing and security boundary

- The archive includes `LICENSE` identifying the Merserk source as MIT.
- NVIDIA DLSS material is accompanied by `LICENSE-NVIDIA-DLSS.txt`; NVIDIA
  binary rights remain governed by that license and any applicable terms.
- The archive includes `LICENSE.GPL` and `LICENSE.LGPL` for mpv-related
  material, so those files cannot be copied into this MIT project without a
  separate packaging/license review.
- Several Neuroframe binaries were reported `NotSigned` by Windows
  Authenticode inspection. This is an observation, not a safety conclusion.
- Defender scanning was not used as a release or execution gate in this
  audit, and no file from the archive was executed.

## Required-file and ABI audit

The release layout contains separate `dlssnr`, `dlssg`, and `rtx_video` runtime
families. The three `dlssnr` files currently identified by the static inspector
are not sufficient evidence for execution: the archive also contains other
neural/runtime DLLs, an embedded Python application, FFmpeg/FFprobe, mpv,
configuration, and NVIDIA license material. A complete dependency graph for a
standalone project adapter has not been established. D3D12, CUDA/NVAPI/NGX,
driver, model/resource, loader-search-path, and environment assumptions remain
unvalidated. No v9 file has been executed.

## Integration decision

The v9 archive is represented in the runtime manifest as a separately staged
**selective-extraction, static-only DLSS5 Neuroframe candidate**. The complete
archive hash is required, the entire member namespace is checked for traversal,
absolute-path, and case-insensitive collision hazards, and only the explicit
allowlist is extracted. Ignored archive members are never executed. It does
not replace the validated Phase 4D legacy v3 runtime and is not redistributable.
Before any execution, the project must define the exact DLL boundary, D3D12/CUDA
interoperability path, process/network boundary, required file allowlist, and
synthetic RTX 3070 Ti self-test. Until those gates pass, the supported project
path remains the preserved legacy v3 implementation.

The reusable static gate is:

```powershell
python tools/inspect_dlss5_candidate.py <candidate.zip> --sha256 F531426E0B6C935C2ECC6299121F910E3921FC6CBD589C9A3B95A78A1D589D71
```

It validates the archive digest and member paths, reports binary/license
inventory, and explicitly performs no extraction or execution.

## Control coverage

This is a v9 candidate mapping, not a native-validation claim:

| Control | Status |
|---|---|
| Source/100%, 75%, 50%, 25% processing resolution | STATICALLY MAPPED; native behavior unvalidated |
| NR Style, NR Intensity, Local Tone, Local Structure, Skin Structure | STATICALLY MAPPED from project controls; not proven to be v9-native |
| Automatic Mask, Tone Preservation, Face/Skin Protection | NOT ESTABLISHED for v9 |
| Color Strength, Grain Preservation, Multi Pass, Shimmer Suppression, Custom Mask | NOT IMPLEMENTED / no v9 ABI evidence |

The legacy Phase 4D v3 controls remain separate. The existing `67%` control is
legacy recomposition behavior and is not presented as a v9 processing choice.
