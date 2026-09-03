# Standalone DLSS Super Resolution Host

This is a separate D3D12/NGX backend. It does not use the Merserk DLSS5
protocol-v4 worker.

The build references the locally staged NVIDIA SDK at
`third_party/local/nvidia-dlss-sdk-full`; NVIDIA headers and libraries are not
copied into this source tree. Build output and runtime self-test data belong in
the ignored `runtime/dlss-sr-host` directory.

The stable project identifier is `9f4c4f6d-2f4e-4e88-9e4d-4e8f4d2b7b1a`.
