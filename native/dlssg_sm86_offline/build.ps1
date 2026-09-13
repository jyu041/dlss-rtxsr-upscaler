param([string]$NgxSdk = 'C:\Users\mark\AppData\Local\Temp\dlssg-phase3-research\DLSS', [string]$NvApi = 'C:\Users\mark\Desktop\dlss-community-research\renodx\external\NVAPI', [string]$Output = "$PSScriptRoot\bin")
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
$developerEnvironment = cmd /d /s /c "call `"$vcvars`" && set"
$includeLine = $developerEnvironment | Where-Object { $_ -cmatch '^INCLUDE=' } | Select-Object -First 1
$libLine = $developerEnvironment | Where-Object { $_ -cmatch '^LIB=' } | Select-Object -First 1
$pathLine = $developerEnvironment | Where-Object { $_ -match '^Path=' -and $_ -match '\\VC\\Tools\\MSVC\\' } | Select-Object -First 1
if (-not $includeLine -or -not $libLine -or -not $pathLine) { throw 'Visual Studio x64 environment activation failed' }
[Environment]::SetEnvironmentVariable('INCLUDE', $includeLine.Substring($includeLine.IndexOf('=') + 1), 'Process')
[Environment]::SetEnvironmentVariable('LIB', $libLine.Substring($libLine.IndexOf('=') + 1), 'Process')
[Environment]::SetEnvironmentVariable('Path', $pathLine.Substring($pathLine.IndexOf('=') + 1), 'Process')
$inc = Join-Path $NgxSdk 'include'; $lib = Join-Path $NgxSdk 'lib\Windows_x86_64\x64'
cl /nologo /std:c++17 /O2 /EHsc /W4 /Zi /MD /I"$inc" /I"$NvApi" /Fe:"$Output\dlssg_sm86_offline.exe" "$PSScriptRoot\dlssg_sm86_offline.cpp" "$PSScriptRoot\resource_pipeline.cpp" "$PSScriptRoot\community_run2x.cpp" /link /DEBUG /LIBPATH:"$lib" nvsdk_ngx_d.lib d3d12.lib dxgi.lib version.lib advapi32.lib user32.lib bcrypt.lib
