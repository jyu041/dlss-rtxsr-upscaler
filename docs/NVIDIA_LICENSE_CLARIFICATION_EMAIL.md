# Optional NVIDIA License Clarification Email

To: nvidia-rtx-license-questions@nvidia.com
Subject: DLSS/NGX object-code distribution in an MIT Windows application

Hello NVIDIA Licensing,

I maintain NVIDIA Video Enhancer, an open-source MIT-licensed Windows
application. We authored a C++ DLSS-G worker using NVIDIA NGX/DLSS headers and
`nvsdk_ngx_d.lib`. The validated worker SHA-256 is
`C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916`; its
source is public.

We do not intend to redistribute the community `version.dll`, the official
NVIDIA feature runtime, or driver `nvofapi64.dll`; users obtain those
separately. We intend to distribute the compiled project worker as part of an
application release, with project code MIT-licensed and NVIDIA materials
identified under their applicable terms.

Could you confirm the permitted object-code application distribution, required
terms/notices and attribution/marks, compatibility with an MIT application
without relicensing NVIDIA portions, whether any notification is needed for a
public non-commercial beta, and requirements for a future commercial release?

Thank you,
[name]
