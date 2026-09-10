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
steady-state processing. The previous benchmark's FPS represented Feature-18
submit throughput only. The corrected benchmark separates Feature submit,
motion-plus-submit, and complete processing-loop throughput. Submit/round-trip
wall time is CPU-side protocol time, not GPU time. Optical flow is a major
measured cost on the RTX 3070. Effect metrics are deliberately permissive
diagnostics and do not judge image quality; readiness continues to require the
existing Feature-18 verification until a controlled hardware baseline justifies
stronger gating.

The benchmark samples whole-GPU memory with `nvidia-smi`, so VRAM values are
approximate and include other programs. Reports contain local filesystem paths;
redact them before posting publicly.

Reduced-resolution NR is experimental. Both optical flow and Feature 18 run at
the selected working resolution, then the neural residual is applied to the
native frame so output dimensions remain native. 100% is the default and
bypasses this path. Smaller working scales may trade neural-detail fidelity for
speed and require DLSS5 output scale 1.0x. Effect magnitude and relative MAE
values measure the magnitude of the neural edit, not image quality. Future
research will evaluate this speed/fidelity tradeoff; decoder/encoder pipelining
is not part of this sprint.

## Commands

```powershell
python -m src.backends.dlss5_diagnostics
python -m src.backends.dlss5_diagnostics --self-test
python -m src.backends.dlss5_benchmark --frames 24 --warmup 4
python -m src.backends.dlss5_benchmark --resolutions 1920x1080 --working-scales 1,0.75,0.6666666667,0.5 --frames 24 --warmup 4
```

The commands are opt-in. Diagnostics are passive by default; none downloads
files or changes firewall rules. Benchmark reports are written under ignored
`logs/`.

## Community Research References

- [DLSS5-NeuralScreen](https://github.com/perseval-BLR/DLSS5-NeuralScreen)
- [neural-upstream](https://github.com/matiasLombo/neural-upstream)
- [dlss5-video-player](https://github.com/2600th/dlss5-video-player)
- [OptiScaler_DLSSNR](https://github.com/Dagherbou/OptiScaler_DLSSNR)
