# Third-Party Notices

Project-authored source remains MIT-licensed. This file does not relicense
third-party material.

## NVIDIA NGX / DLSS SDK

C55 was built with NVIDIA DLSS/NGX SDK repository commit
`374959484e79a640feaba44c93ac8cfb0a03f5b5`. The exact local `LICENSE.txt`
SHA-256 is `3027F23CA5A46DD9CB8183FBD522983A86F64D7DAAC5982912BF9F214671F294`,
version `(v. March 14, 2024)`. It remains under NVIDIA terms, not MIT. The
license grants object-code distribution when incorporated into an application
with material additional functionality, while prohibiting stand-alone SDK
distribution and open-source relicensing of NVIDIA SDK material. It also
contains notice, third-party, export, and commercial-release notification
requirements.

## NVIDIA NVAPI headers

The build used the NVIDIA NVAPI lineage at local checkout commit
`87dca625e83fd89a983e19b904e5f3a580da90d2`; `nvapi.h` SHA-256 is
`4EE1BFF7568CEEC72124B8B3E43BF65CCB69DBB878B08C634B128F7EDCD28F3B`.
The accompanying notice is MIT, Copyright (c) 2024 NVIDIA CORPORATION &
AFFILIATES. Preserve its copyright, SPDX, permission, and disclaimer notice.
NVAPI library code is not statically linked by this worker; the worker loads
the system `nvapi64.dll` dynamically.

## NVIDIA Optical Flow headers

The build used `nvOpticalFlowD3D12.h` SHA-256
`D1952D0946A26F1B77E76C320B4DFE9077D946FDC1A6195E01F0460362026305` and
`nvOpticalFlowCommon.h` SHA-256
`FB96FC6061C01EC2C5970ECEBEBACAC7535C033717FF39810CADA1F197C8EC9F` from
header mirror commit `99e8d8eb8f269591e5e4bd5a7f3c248bbbc3a3b9`. Their exact
headers carry NVIDIA MIT-style notices (Copyright (c) 2018-2023 and
2020-2023). Preserve those notices. `nvofapi64.dll` is driver-provided and
is not bundled.

## Community and official runtimes

The beta.2 package includes the official DLSS SR REL `nvngx_dlss.dll` used by
the validated host. It remains NVIDIA material under the applicable NVIDIA
SDK/runtime terms, is not MIT-licensed, and must not be extracted or
redistributed as a stand-alone runtime.

The validated C55 direct-host DLSS-G profile uses `version.dll` and
`dlssg_sm86.ini` from `sdli1995/dlssg_for_sm86` commit
`5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`. The tested `version.dll` SHA-256
is `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`.
That upstream commit carries GPLv3/source ancestry plus separate NVIDIA and
third-party material notices; this repository does not claim a standalone
redistribution grant for those binaries.

Accordingly, the source repository does **not** commit or redistribute that
external runtime. On the user's explicit `setup.bat` action, Runtime Manager
downloads the two exact files directly from their pinned public upstream commit,
verifies their recorded hashes and sizes, and installs them locally under
`runtime/dlssg/legacy/`. The `legacy` profile name is retained for identity
compatibility; it is the normal validated C55 path because it has retained RTX
3070 Ti 2X/3X/4X evidence.

The pinned NVIDIA Streamline DLSS-G provider is handled through the same
non-redistribution model: setup downloads it directly from the recorded public
NVIDIA source and verifies its exact identity before use. The newer SM86 0.3.1
proxy-generation files remain an explicit experimental candidate in Runtime
Manager; they are not silently substituted for the validated C55 direct-host
profile. All upstream licenses and terms continue to apply.

The optional DLSS 5 v3 provisioner follows the same non-redistribution model.
After explicit user opt-in it downloads `DLSS.5.Visual.Enhancer.v3.0.zip`
directly from the public `Merserk/dlss5-visual-enhancer` v3.0 release, verifies
the pinned release archive and the five exact runtime-file hashes, and keeps
only the files required by the retained Feature-18 protocol client. The source
repository's MIT license does not relicense those packaged NVIDIA, ReShade,
RenoDX, or project-specific prebuilt runtime files. Their controlling licenses
and distribution terms continue to apply. The setup flow records Authenticode
observations, requires a clean Microsoft Defender scan for automatic approval,
and does not copy these binaries into this Git repository or a project release.

Visual Enhancer v10 remains a separately staged DLSS 5 Neuroframe candidate
and is not substituted for the validated v3 execution path. Its upstream
runtime files remain under their respective licenses; the project's explicit
v10 experimental application mode adds execution/containment gates without
relicensing or redistributing those files. The earlier v9 candidate is retained
as historical static-audit evidence.

FFmpeg/FFprobe and Python dependencies retain their own upstream licenses.
