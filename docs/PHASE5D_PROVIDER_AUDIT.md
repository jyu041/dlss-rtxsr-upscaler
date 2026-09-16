# Phase 5D provider and candidate audit

This is local development evidence for the `phase5-portable-runtime-refresh`
branch. It is not a release approval and contains no bundled third-party
binaries.

## Official NVIDIA provider

The provider source is the official NVIDIA-RTX/Streamline GitHub release
`v2.14.1`, asset `streamline-sdk-v2.14.1.zip`.

- archive size: `275,994,000` bytes
- archive SHA-256: `92C4D954631A1710DA86CA3FA8D5034F2B9503838C95FC4AE977AE149319781B`
- selected member: `bin/x64/nvngx_dlssg.dll`
- provider size: `7,460,976` bytes
- provider SHA-256: `FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82`
- FileVersion/ProductVersion: `310.9.1.0`
- Authenticode: valid, signer `NVIDIA Corporation`

The separate development member was not conflated with the release provider.
The runtime manager extracts only the release provider and the accompanying
`bin/x64/nvngx_dlss.license.txt` notice into the ignored local managed runtime.
The component is `UPSTREAM_DOWNLOAD`, explicit-install only, and
`redistributable=false` pending separate distribution review.

## Candidate result

The exact C55 worker and pinned community 0.3.1 files passed their static
identity gates. The first required 2X external-motion native attempt then
failed during worker startup. Diagnostic output showed the official provider
initialized, but the candidate reported `FRAME_GENERATION_AVAILABLE=0`, missing
MFG capability parameters, and the protocol pipe closed before `HELLO`.

Consequently 3X, 4X, NVOF, application integration, performance comparison,
and attestation writing were not attempted. The candidate remains
`VALIDATION_REQUIRED`; no partial PASS attestation is accepted.

The validator now requires protocol-v4 reset no-output, exact `M-1` outputs,
ordered generated-group semantics, zero disable-interpolation, exact dimensions
and pixel format, exact output byte counts, distinct deterministic frames,
external motion plus NVOF paths, and owned-process-tree cleanup on timeout or
failure.
