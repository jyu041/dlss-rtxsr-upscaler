# Troubleshooting

Run `python -m src.core.diagnostics` inside the dedicated Conda environment
first. If FFmpeg is unavailable, install a compatible FFmpeg/FFprobe build and
ensure both commands are on `PATH`.

If RTX VSR is unavailable, verify the official `nvidia-vfx` package and NVIDIA
driver. If DLSS SR is unavailable, verify the native host, the approved
`nvngx_dlss.dll` hash, and its self-test result. If DLSS5 is unavailable, check
the local approval manifest, all exact hashes, the signed Feature-18 evidence,
and the worker's exact outbound Firewall block.

The application does not download replacement runtimes or silently switch
backends. The DLSS paths are SDR-oriented and do not promise HDR preservation.
