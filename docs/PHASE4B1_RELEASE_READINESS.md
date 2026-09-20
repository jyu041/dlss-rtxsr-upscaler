# Phase 4B1 Release Readiness

Status: `READY FOR BETA PACKAGING` (subject to package assembly and notice review)

C55 classification: **A — PUBLIC REDISTRIBUTION SUPPORTED BY AVAILABLE LICENSE EVIDENCE**.
This is an evidence classification, not legal advice. Optional written NVIDIA
clarification is supporting evidence only and is not a release gate.

The Phase 4A backend baseline is frozen at public `e65bc934a096787468228f9f0ce5eb87063025f9`.
This milestone adds release-readiness assessment only; it does not change
protocol v4, MFG semantics, NVOF, GPU flow, synchronization, readback, or
scene-cut behavior.

## User journey audit

| Stage | Classification | Evidence / blocker |
|---|---|---|
| GitHub source checkout | Automatic/manual | User installs Git and checks out the public repository. |
| Python/Conda | Documented manual | `setup.bat` creates/updates the dedicated environment; Conda is not bundled. |
| Python dependencies | Automatic after approval | `environment.yml` uses declared NVIDIA and PyTorch indexes; package terms remain applicable. |
| FFmpeg/FFprobe | Documented manual | Full Gyan build on PATH; setup verifies both NVENC encoders. |
| Microsoft VC++ runtime | Documented manual | C55 `/MD` imports MSVCP140/VCRUNTIME140/VCRUNTIME140_1 plus UCRT API sets; install the Microsoft x64 redistributable separately. |
| Project worker | Blocked for a clean public checkout | Native source/build instructions exist, but the validated C55 worker is not in Git. |
| Community runtime | Documented manual / user-supplied | Not downloaded or bundled; exact known identity is hash-gated. |
| Official NVIDIA runtime | Documented manual / user-supplied | Not downloaded or bundled; licensing and acquisition remain vendor-controlled. |
| Configure paths | Automatic persistence after manual entry | UI stores values in ignored `config/settings.local.json`; no environment variable is required. |
| App/backend/diagnostics | Automatic after prerequisites | Backend refuses operation when any required layer is absent; no fallback. |
| First render | Blocked until readiness | `python tools\check_dlssg_readiness.py` is the authoritative preflight. |

## Dependency and ownership matrix

| Component | Supplier / redistribution | Expected location and check | Required | Build/runtime |
|---|---|---|---|---|
| Project worker | Project source; validated binary not currently redistributed | User-managed worker path; exact C55 SHA-256 | Yes | Runtime |
| Community `version.dll` | External community project; terms/trust decision pending user | Absolute path; exact C844...AE7C2 hash | Yes | Runtime |
| Official NVIDIA NGX runtime | NVIDIA; vendor terms; user supplied | Absolute directory; must be non-empty | Yes | Runtime |
| `nvofapi64.dll` | NVIDIA driver | `%SystemRoot%\System32\nvofapi64.dll` | Yes | Runtime |
| FFmpeg/FFprobe | User-supplied build | PATH; `h264_nvenc` and `hevc_nvenc` | Yes | Runtime |
| NGX/NVAPI/NVOF headers/libs | NVIDIA SDKs, locally staged | Native build inputs only; never committed | Build only | Build |

The worker source imports system `d3d12`, `dxgi`, `advapi32`, `user32`,
`bcrypt`, and `version` libraries, loads `nvapi64.dll` from System32, loads
`nvofapi64.dll` from System32, dynamically loads the supplied community DLL,
and initializes the supplied official NGX directory. The exact local NGX/DLSS
snapshot is repository commit `374959484e79a640feaba44c93ac8cfb0a03f5b5`;
its `LICENSE.txt` SHA-256 is
`3027F23CA5A46DD9CB8183FBD522983A86F64D7DAAC5982912BF9F214671F294`, version
`(v. March 14, 2024)`. That license grants distribution of SDK material
incorporated in object code into an application with material additional
functionality, while prohibiting stand-alone SDK distribution and open-source
relicensing of NVIDIA SDK material. It also specifies notice, third-party,
export, and pre-commercial-release notification obligations. This is the
governing evidence for classification A; optional written clarification is not
required before a non-commercial/public beta. No C55 binary is published by
this milestone.

## Distribution decision

Recommendation: **Option B — an NVIDIA Video Enhancer release archive/application
package containing the application, validated C55 worker, project docs, and
required notices, but not the community `version.dll`, official NVIDIA
runtime, or driver `nvofapi64.dll`**. This uses the object-code application
grant without presenting the SDK as a stand-alone product and keeps all
external runtime acquisition user-controlled.

The package must keep project-owned source under MIT while identifying NVIDIA
SDK material and other third-party portions under their own terms. See
`THIRD_PARTY_NOTICES.md` and `docs/legal/BINARY_DISTRIBUTION_NOTICES.md`.

## Hardcoded assumptions and security

Machine-specific paths occur in developer-only native build/research scripts
and test fixtures. They are not application runtime defaults. Release-facing
configuration uses user-entered absolute paths, ignored local settings, and
redacted readiness output. The app remains localhost-only, analytics are
disabled, no runtime download or upload is performed, and no test media or
runtime evidence is part of the public Git history.

## Optional NVIDIA clarification

`docs/NVIDIA_LICENSE_CLARIFICATION_EMAIL.md` contains a factual email draft.
It is not sent, and no response is required before a non-commercial/public
beta under this evidence-based classification. Commercial release notification
must still be handled if required by the exact applicable license.

## Beta gate

The technical/legal evidence gate is satisfied for C55 under the exact local
SDK license, provided the package includes the required notices and does not
bundle the unresolved community or official runtime binaries. Packaging work
and final notice review remain before an actual beta artifact is published.
