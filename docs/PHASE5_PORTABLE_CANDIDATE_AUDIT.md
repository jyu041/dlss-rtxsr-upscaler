# Phase 5 portable candidate audit

Audit date: 2026-09-16

The deterministic builder produced this local, non-published candidate from
source commit `d6781fde2f99e1820900e773fee362870785255f`:

| Field | Value |
|---|---|
| Candidate ZIP size | `345340032` bytes |
| Candidate ZIP SHA-256 | `A3B3E3A0D10FFC254695FB004305F30469EC28A88A181160402F7510E9E47C89` |
| Source inputs | Explicitly supplied v9 embedded Python and FFmpeg directories |
| Neural/NVIDIA runtime contents | Not staged |
| Publication status | Local candidate only; no tag/release/upload |

The candidate contains the project source plus the explicitly supplied portable
Python and FFmpeg files. It is not a release recommendation: the Python,
FFmpeg, and other third-party terms still require packaging review, and no
DLSS5 Neuroframe or community MFG binary is bundled by this project.

The candidate must be checked through `build-manifest.json` and
`SHA256SUMS`; the portable integrity checker does not execute the staged
interpreter or media tools.
