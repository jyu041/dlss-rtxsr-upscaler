# Phase 5 upstream research

Research snapshot: 2026-09-16. URLs and identifiers below are public
provenance references, not a grant to redistribute third-party binaries.

## DLSS-G for SM86

- Repository: [sdli1995/dlssg_for_sm86](https://github.com/sdli1995/dlssg_for_sm86)
- Current release/tag: `0.3.1`
- Current tag/HEAD: `117faf5c70333b34160f5d21d01c222261cc5af1`
- Exact pinned root files independently downloaded from that commit:
  `version.dll` is 29,676,832 bytes with SHA-256
  `3D4C7D537A6E71E3A9D41FFC6487E054B26C56D27B7C0825D39EAA7EF0C7E86D`;
  `dlssg_sm86.ini` is 2,727 bytes with SHA-256
  `231574047C4989D292E592802102D2437FC636B56E535E8D70D403F20D4CCAFC`;
  `THIRD_PARTY_NOTICES.txt` is 3,349 bytes with SHA-256
  `AC3B44AB30A4235EDD18FECA1AB4F802D57C8D3D0EE4878DC77B81A6B127155F`.
  The previously recorded 15,667,520-byte / 581-byte identities belong only
  to the legacy `5f62ff44` generation.
- The current README describes a proxy around an unmodified factory runtime,
  optimized Ampere kernels, and a 310.9 runtime path with a five-generated-
  frame ceiling (6X where the game supports Dynamic MFG). It reports 2X/3X/4X
  compatibility and 6X as game/runtime-dependent, not as a universal worker
  guarantee.
- The repository has no GitHub SPDX license classification. Its notices state
  GPLv3 source ancestry and separate NVIDIA/third-party runtime and kernel
  material. This project must not copy that GPL source or bundle its binaries
  without a separate distribution decision.
- Recommended Phase 5 integration: keep C55 and the old runtime untouched;
  obtain a newer runtime only through an explicit, user-visible
  `UPSTREAM_DOWNLOAD` installation and test it as a separate candidate.
- The 0.3.1 commit message identifies this release as a 310.9 rebuild and
  changes the factory ceiling to 3 generated frames (4X); upstream also
  describes an optional 5-generated-frame/6X path. This is upstream evidence,
  not C55 compatibility evidence. The root proxy has blank PE version fields
  and an untrusted self-signed Authenticode chain; no Defender scan was used as
  a release gate.

## DLSS 5 Visual Enhancer

- Repository: [Merserk/dlss5-visual-enhancer](https://github.com/Merserk/dlss5-visual-enhancer)
- Current release: signed `v9.0`, commit
  `c95c050ead79b9409f140e0b2a66a7b91cffb258`.
- Release artifact: `DLSS.5.Visual.Enhancer.v9.0.zip`,
  [GitHub release asset](https://github.com/Merserk/dlss5-visual-enhancer/releases/download/v9.0/DLSS.5.Visual.Enhancer.v9.0.zip),
  509,001,461 bytes, SHA-256
  `F531426E0B6C935C2ECC6299121F910E3921FC6CBD589C9A3B95A78A1D589D71`.
- The source repository is classified MIT. The release ZIP is still a
  separate binary/licensing question and is not bundled here. Its documented
  Neuroframe Engine is a materially different, self-contained GPU-focused
  architecture from this project's legacy ReShade protocol client.
- Recommended integration: treat it as an explicit user-supplied or direct
  upstream-download candidate until its contained binary notices and RTX30
  behavior are independently audited. Do not replace the validated legacy
  path automatically.

## NVIDIA Streamline

- Repository: [NVIDIA-RTX/Streamline](https://github.com/NVIDIA-RTX/Streamline)
- Current release: `v2.14.1`, published 2026-09-08.
- Windows SDK asset: `streamline-sdk-v2.14.1.zip`, 275,994,000 bytes, SHA-256
  `92C4D954631A1710DA86CA3FA8D5034F2B9503838C95FC4AE977AE149319781B`.
- The repository advertises version 2.14.1 and Dynamic MFG interfaces. It
  states that the DLSS-G plugin is supplied as prebuilt DLLs even though other
  Streamline pieces can be rebuilt. GitHub reports `NOASSERTION` for the
  repository license, so no SDK/runtime binary is bundled by this milestone.
- Streamline is an application-integration framework, not evidence that a
  standalone offline video worker can safely consume a newer MFG runtime.

## Official NVIDIA distinction

- NVIDIA's [current DLSS overview](https://developer.nvidia.com/rtx/dlss)
  describes DLSS 4.5 Dynamic/6X MFG and identifies Multi Frame Generation as
  powered by fifth-generation Tensor Cores on RTX 50 Series and RTX PRO
  Blackwell GPUs.
- That official scope does not establish RTX30 DLSS5 or official RTX30 MFG
  support. The project's RTX30 results remain community-runtime research on
  the validated RTX 3070 Ti / Windows 11 build 26200 / driver 610.62 setup.

## Phase 5 compatibility hypotheses

1. C55 may accept a newer proxy/runtime pair because the external protocol is
   intentionally runtime-gated, but this must be tested at 2X/3X/4X with only
   synthetic input and without changing C55.
2. 5X/6X cannot be enabled by changing a Python tuple: worker buffers,
   protocol semantics, generated-index ordering, and terminal-frame policy
   require independent validation.
3. The v9 Neuroframe Engine may offer a better native/source-resolution DLSS5
   architecture, but its release binaries remain external until their notices,
   signatures, hashes, and RTX30 behavior are audited.

## Runtime policy

The manager introduced in Phase 5 uses explicit categories:

- `PROJECT_BUNDLED`: project-owned artifacts with established rights.
- `UPSTREAM_DOWNLOAD`: explicit download from a pinned authoritative URL.
- `USER_SUPPLIED`: manually provided local experimental runtime.
- `SYSTEM_COMPONENT`: driver/system files such as `nvofapi64.dll`.

No normal startup path downloads a runtime. Candidate files may be explicitly
downloaded and hash-verified, but candidate presence is only static verification;
native activation additionally requires a current C55 compatibility attestation.
