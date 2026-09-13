# Phase 5N — Evaluate/Readback Status

## Result

`EVALUATE_FAILED`

The complete Phase 5N 2X path was not executed. The existing host still stops
after the proven community CreateFeature boundary; it does not yet contain a
compliant uploaded synthetic-input, measured-Evaluate, fence, and readback
implementation. No malformed Evaluate call was submitted and no community
GPU generation attempt was made.

## Established prerequisites

- Primary HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community HEAD: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Community DLL SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- GPU: `NVIDIA GeForce RTX 3070 Ti`
- Full DXGI/NVAPI LUID match: `1`
- Native architecture: `0x170`
- Official NGX Init: `0x00000001`
- Official parameter allocation: `0x00000001`
- Community Init: `0x00000001`
- Community CreateFeature: `0x00000001`
- Feature handle: non-null

## Host status

The existing `native\dlssg_sm86_offline\` host contains selftest,
parameter-probe, shutdown-probe, runtime-probe, community-init-probe, and
community-create-probe modes. It does not yet provide all of the following as
one validated `--run-2x` operation:

- default-heap Frame A/Frame B color, depth, and motion textures;
- row-pitch-correct upload staging and synchronization;
- complete public DLSS-G evaluation parameter population;
- reset/history Evaluate;
- exactly one measured Evaluate;
- output transition, copyable-footprint readback, and CPU statistics;
- persisted generated output and A/B comparison.

## Execution

- Phase 5N `--run-2x`: **NOT RUN**
- Community Evaluate calls: `0`
- Swapchain: `0`
- Present: `0`
- Output file: none
- Readback/hash: none
- Retries: `0`

The GPU remained healthy after the prior Create probe. No driver/provider,
registry, HAGS, TDR, VBIOS, clock, voltage, or power changes were made.

## Next step

`FIX_EXACT_EVALUATE_OR_OUTPUT_BOUNDARY`

Complete and validate the resource/upload/fence/readback implementation before
the one authorized community measured-Evaluate attempt. Do not treat the
Create success as evidence that generated output works.

## Git

- No commit.
- No push.
