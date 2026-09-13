# NVIDIA Optical Flow SDK dependency

The native DLSS-G worker dynamically loads the driver-supplied
`nvofapi64.dll`. No NVIDIA runtime binary is redistributed here.

Building the D3D12 NVOF integration requires NVIDIA's public
`nvOpticalFlowD3D12.h` and `nvOpticalFlowCommon.h`. Obtain them from the
official NVIDIA Optical Flow SDK download, accept NVIDIA's applicable terms,
and either:

- set `NVOF_SDK` to the directory containing those headers;
- pass `-NvOfSdk <directory>` to `native/dlssg_sm86_offline/build.ps1`; or
- stage them under `third_party/local/nvidia-optical-flow-sdk/` (ignored by Git).

The NVIDIA header notice grants MIT-style permission for the header files and
requires preservation of its copyright/permission notice. The project does not
commit SDK payloads or driver DLLs.

Development provenance used for the first API-v5 D3D12 build:

- official NVIDIA `NVIDIAOpticalFlowSDK` repository commit
  `edb50da3cf849840d680249aa6dbef248ebce2ca` (common headers/samples);
- API-v5 D3D12 header mirror commit
  `99e8d8eb8f269591e5e4bd5a7f3c248bbbc3a3b9`, inspected only as a temporary
  compile-time source while NVIDIA's Windows SDK download required login.

Production/release builds should use the official SDK package.
