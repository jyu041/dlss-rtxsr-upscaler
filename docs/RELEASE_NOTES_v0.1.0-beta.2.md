# NVIDIA Video Enhancer v0.1.0-beta.2

Second public beta for the validated Windows 10 / RTX 3070 Ti 8 GB / NVIDIA
driver 610.62 configuration.

RTX VSR and standalone DLSS SR are turnkey beta backends on that exercised
configuration. DLSS-G remains available with user-supplied external runtimes;
DLSS 5 remains experimental and is not bundled.

The application package includes the project-owned DLSS SR host and the exact
official NVIDIA REL `nvngx_dlss.dll` under the applicable NVIDIA terms. The
package also includes the validated C55 worker. Project source remains MIT;
NVIDIA material remains under NVIDIA terms, and no NVIDIA endorsement is
implied.

DLSS SR requires an explicit first-use local self-test. RTX VSR installs the
pinned `nvidia-vfx` package during setup. Unsigned project binaries may trigger
normal Windows reputation warnings; do not disable security software.

Identities:

- Source commit: recorded in `release-manifest.json`
- C55: `C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916`
- DLSS SR host: `E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34BB`
- Official REL runtime: `3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983`
- Package SHA-256: recorded in `SHA256SUMS.txt` after candidate creation

This beta is not a universal RTX 30-series or NVIDIA compatibility claim.
