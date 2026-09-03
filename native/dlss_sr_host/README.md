# Standalone DLSS Super Resolution Host

This is a separate D3D12/NGX backend. It does not use the Merserk DLSS5
protocol-v4 worker.

The build references the locally staged NVIDIA SDK at
`third_party/local/nvidia-dlss-sdk-full`; NVIDIA headers and libraries are not
copied into this source tree. Build output and runtime self-test data belong in
the ignored `runtime/dlss-sr-host` directory.

The stable project identifier is `9f4c4f6d-2f4e-4e88-9e4d-4e8f4d2b7b1a`.

`stream <input_w> <input_h> <output_w> <output_h> [mode] [preset]` keeps one
NGX session alive and exchanges binary frames over stdin/stdout. The input
header is seven little-endian `uint32` values: magic, frame number, width,
height, reset, RGBA8 color byte count, and float32x2 motion byte count. The
output header is six little-endian `uint32` values: magic, frame number, width,
height, status, and RGBA8 output byte count. Pixels are tightly packed RGBA8,
top-left origin; motion vectors are backward pixel-space vectors in the
DLSS convention. Diagnostics go to stderr only.

Video frames have no engine jitter or real depth. The baseline sends zero
jitter, constant depth, and reset=true for the first frame or a detected cut;
subsequent coherent frames retain NGX history.
