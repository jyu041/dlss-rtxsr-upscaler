param([string]$NgxSdk = 'C:\Users\mark\AppData\Local\Temp\dlssg-phase3-research\DLSS', [string]$NvApi = 'C:\Users\mark\Desktop\dlss-community-research\renodx\external\NVAPI', [string]$Output = "$PSScriptRoot\bin")
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
cmd /d /s /c "call `"$vcvars`" && set" | ForEach-Object { if ($_ -cmatch '^(INCLUDE|LIB|PATH)=(.*)$') { Set-Item "Env:$($Matches[1])" $Matches[2] } }
$inc = Join-Path $NgxSdk 'include'; $lib = Join-Path $NgxSdk 'lib\Windows_x86_64\x64'
cl /nologo /std:c++17 /O2 /EHsc /W4 /Zi /MD /I"$inc" /I"$NvApi" /Fe:"$Output\dlssg_sm86_offline.exe" "$PSScriptRoot\dlssg_sm86_offline.cpp" "$PSScriptRoot\resource_pipeline.cpp" "$PSScriptRoot\community_run2x.cpp" /link /DEBUG /LIBPATH:"$lib" nvsdk_ngx_d.lib d3d12.lib dxgi.lib version.lib advapi32.lib user32.lib bcrypt.lib
