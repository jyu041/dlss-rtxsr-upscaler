# DLSS5 Research

DLSS 5 Neural Rendering / Feature 18 is experimental in this project. Recent
community work demonstrates experimental execution on older RTX architectures,
including Ampere, but this is **not official NVIDIA RTX 30 DLSS5 support**.
This repository neither ships nor downloads NVIDIA or community NR runtime
binaries. Runtime approval, exact hash, and outbound firewall policy are
unchanged.

Successful NGX calls alone are not performance or effectiveness evidence. The
128x128 five-frame self-test remains a contract check only. Meaningful
benchmark resolutions begin at 960x540 and separate session initialization from
steady-state processing. Submit/round-trip wall time is CPU-side protocol time,
not GPU time. Effect metrics are deliberately permissive diagnostics and do
not judge image quality; readiness continues to require the existing Feature-18
verification until a controlled hardware baseline justifies stronger gating.

The benchmark samples whole-GPU memory with `nvidia-smi`, so VRAM values are
approximate and include other programs. Reports contain local filesystem paths;
redact them before posting publicly. Future research will evaluate
reduced-resolution NR and residual composition separately. This sprint does not
implement that pipeline.

## Commands

```powershell
python -m src.backends.dlss5_diagnostics
python -m src.backends.dlss5_diagnostics --self-test
python -m src.backends.dlss5_benchmark --frames 24 --warmup 4
```

The commands are opt-in. Diagnostics are passive by default; none downloads
files or changes firewall rules. Benchmark reports are written under ignored
`logs/`.

## Community Research References

- [DLSS5-NeuralScreen](https://github.com/perseval-BLR/DLSS5-NeuralScreen)
- [neural-upstream](https://github.com/matiasLombo/neural-upstream)
- [dlss5-video-player](https://github.com/2600th/dlss5-video-player)
- [OptiScaler_DLSSNR](https://github.com/Dagherbou/OptiScaler_DLSSNR)
