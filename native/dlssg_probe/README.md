# DLSSG Capability Probe

This is a capability-only D3D12/NGX probe. It enumerates adapters, selects one
`NVIDIA GeForce RTX 3070`, creates a D3D12 device, initializes NGX, reads the
official capability parameter map, prints JSON, and shuts everything down.

It does not create or evaluate a DLSS Frame Generation feature, allocate frame
generation resources, create a command queue, submit GPU work, use CUDA, or
load a proxy DLL. The public source does not bundle an NVIDIA runtime.

Build outside this repository using an external official NVIDIA DLSS SDK clone
from [NVIDIA/DLSS](https://github.com/NVIDIA/DLSS). The SDK headers and import
library are not vendored in this repository:

```powershell
$env:DLSS_SDK = 'C:\path\to\NVIDIA\DLSS'
powershell -ExecutionPolicy Bypass -File native\dlssg_probe\build.ps1 -NgxSdk $env:DLSS_SDK -Output "$env:TEMP\dlssg-probe\bin"
```

Run one probe with an external, NVIDIA-signed `nvngx_dlssg.dll` beside the
executable and a 15-second timeout. Do not use a community runtime or bypass
reported capability values.

## Tested Result

Using an official NVIDIA-signed `nvngx_dlssg.dll` on a GeForce RTX 3070,
NGX initialization and the capability query both succeeded. The
`FrameGeneration_Available` parameter returned `false`; the
`MultiFrameCountMax` query was unsupported and returned `0xBAD00010`.

This applies only to the tested official-runtime configuration. It does not
claim that Frame Generation is physically impossible on Ampere. No Frame
Generation feature was created or evaluated, and this probe does not bypass
NVIDIA hardware or runtime capability checks.
