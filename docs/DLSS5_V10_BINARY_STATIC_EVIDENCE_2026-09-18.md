# DLSS5 Visual Enhancer v10 Binary Static Evidence — 2026-09-18

This is retained static evidence for the exact upstream v10 archive. No DLL in
the archive was loaded or executed.

## Evidence source

GitHub Actions research audit:

- workflow: `research-v10-static-audit`
- run ID: `35311872691`
- branch: `research/mfg-0.3.3-dlss5-v10`
- audited source commit: `7781107b89057f4d62d7c0a35fc3c1e90e7d9c31`
- JSON artifact ID: `10533676019`
- JSON artifact ZIP digest:
  `sha256:c293ce1f6ca36a8c1929153241aeb875f2124ceddc194deeedf7ef0097ecb96a`

The workflow verified the archive identity before extraction and asserted
`static_only=true` and `executed=false`.

## Archive identity

| Field | Value |
|---|---|
| Asset | `Visual.Enhancer.v10.0.zip` |
| Size | `690203043` bytes |
| SHA-256 | `394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515` |

## Extracted identities

| File | Size | SHA-256 | Authenticode |
|---|---:|---|---|
| `nvngx_dlssnr.dll` | 165,830,144 | `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927` | NotSigned |
| `neuroframe_engine_neural_rendering.dll` | 571,904 | `F657D20E569F97DEC25E02141F64354CD4B3E1DC51FA1DFE48ACEEBCC3CC43D5` | NotSigned |
| `neuroframe_caller.dll` | 104,960 | `B3611046837BC2F2E957A694CE0817E3C1B304BD653D0C7A193148E5BDD02437` | NotSigned |
| `LICENSE-NVIDIA-DLSS.txt` | 27,176 | `21B5DAEC892B12BEA692E66BC8FE45CF5902CCAF3A7B831E78050D8859881C37` | n/a |
| `LICENSE-Merserk.txt` | 1,064 | `6D3939094F12AA118F86B6A99C46EA525FF4F203A062C2F377873A3498FFE7EC` | n/a |

All three DLLs are PE32+ x86-64 images.

The unsigned result is a trust-relevant fact, not evidence that the files are
malicious. It means Authenticode cannot independently bind these exact DLLs to
a signing identity; project use must therefore rely on the exact upstream
archive identity and extracted hashes.

## Bridge ABI export result

`neuroframe_engine_neural_rendering.dll` exports 31 named symbols.

Every project-required ABI-6 symbol is present, including:

- `dlss5nr_frame_abi_version`
- `dlss5nr_init`
- `dlss5nr_rebind`
- `dlss5nr_process_v6`
- `dlss5nr_process_cuda_v6`
- `dlss5nr_process_frame_v6`
- `dlss5nr_cuda_supported`
- `dlss5nr_cuda_status`
- `dlss5nr_temporal_status`
- `dlss5nr_scene_score_v1`
- surface create/descriptor/retain/release functions.

The optional `dlss5nr_release_session` export is also present. The bridge also
exports `dlss5nr_shutdown`, but the upstream Python lifecycle intentionally
does not make normal process teardown depend on NGX shutdown.

The caller shim exports:

- `DLSSNR_CallCreate`
- `DLSSNR_CallEvaluate`
- `DLSSNR_CallInit`
- `DLSSNR_CallRelease`

The NVIDIA runtime exposes the expected NGX CUDA, D3D11, D3D12, and Vulkan
entry-point families, including D3D12 Feature create/evaluate/release and
shutdown functions.

## Static import review

Observed imported DLL families:

- `nvngx_dlssnr.dll`: ADVAPI32, KERNEL32, USER32, VERSION.
- `neuroframe_engine_neural_rendering.dll`: D3D12,
  D3DCOMPILER_47, DXGI, KERNEL32, OLE32.
- `neuroframe_caller.dll`: KERNEL32.

No runtime DLL directly imports:

- Winsock / `WS2_32.dll`;
- WinHTTP;
- WinINet;
- URLMon;
- `CreateProcess*`;
- `ShellExecute*`;
- `WinExec`.

The bridge imports ordinary D3D12/DXGI/compiler APIs and filesystem/runtime
functions. The NVIDIA runtime imports registry and normal Win32 runtime APIs.

All three DLLs import dynamic-library/API-resolution functions such as
`LoadLibrary*` and/or `GetProcAddress`. Therefore the absence of direct
network/process-launch imports is useful static evidence but **does not prove**
that no API can be resolved dynamically at runtime.

## Static classification

The exact archive and extracted-file identity gate is now complete.

The binary evidence supports:

- exact upstream archive: PASS;
- exact extracted file identities: PASS;
- x86-64 PE architecture: PASS;
- required bridge ABI-6 exports: PASS;
- direct networking-import review: no direct finding;
- direct process-launch-import review: no direct finding;
- Authenticode: all three DLLs unsigned;
- candidate execution: still **DISABLED**.

This does not validate Feature-18 execution on Ampere and does not change the
validated v3 backend.

## Next gate

The next DLSS5 v10 code phase is an isolated adapter/host design that:

1. uses the pinned ABI-6 contract;
2. is separate from the v3 backend;
3. preserves the v10 process-lifetime NGX lifecycle;
4. fails closed on the exact hashes above;
5. is unit-tested without loading the v10 DLLs;
6. only after that receives a bounded 256x256 / one-frame / 1.0x RTX 3070 Ti
   execution test.
