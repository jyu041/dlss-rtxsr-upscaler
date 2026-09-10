# Troubleshooting

Run `python -m src.core.diagnostics` inside the dedicated Conda environment
first. If FFmpeg is unavailable, install a compatible FFmpeg/FFprobe build and
ensure both commands are on `PATH`.

If RTX VSR is unavailable, verify the official `nvidia-vfx` package and NVIDIA
driver. If DLSS SR is unavailable, verify the native host, the approved
`nvngx_dlss.dll` hash, and its self-test result. If DLSS5 is unavailable, check
the local approval manifest, all exact hashes, the signed Feature-18 evidence,
and the worker's exact outbound Firewall block.

For a passive DLSS5 report run `python -m src.backends.dlss5_diagnostics`.
Use `--self-test` only when an approved runtime and compatible RTX hardware are
already present. For measurements use
`python -m src.backends.dlss5_benchmark`; it writes an ignored JSON report and
continues after a timed-out resolution. An encoder error after a successful
first Feature-18 output is reported as an FFmpeg/NVENC preflight failure, not
as a DLSS5 failure. Inspect and redact local paths before sharing reports.

If reduced NR is selected with a DLSS5 output scale other than 1.0x, the job is
rejected intentionally. Select `100% (Native)` NR working resolution or change
the DLSS5 output scale to 1.0x. Reduced working resolution changes the internal
motion/Feature-18 workload, not the final video dimensions.

If CUDA recomposition cannot select the same unambiguous GPU as the DLSS5
runtime, `auto` records the reason and uses the CPU reference compositor. The
explicit `cuda` option fails instead of silently falling back. CUDA Event times
do not include all host staging and synchronization costs; compare them with
the reported recomposition wall time.

The application does not download replacement runtimes or silently switch
backends. The DLSS paths are SDR-oriented and do not promise HDR preservation.
