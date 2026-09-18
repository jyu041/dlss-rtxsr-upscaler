param(
    [string]$NgxSdk = 'C:\Users\mark\AppData\Local\Temp\dlssg-phase3-research\DLSS',
    [string]$NvApi = 'C:\Users\mark\Desktop\dlss-community-research\renodx\external\NVAPI',
    [string]$NvOfSdk = $env:NVOF_SDK,
    [string]$Output = "$PSScriptRoot\bin-instrumented"
)
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
if (-not $NvOfSdk) {
    $candidate = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'third_party\local\nvidia-optical-flow-sdk'
    if (Test-Path -LiteralPath (Join-Path $candidate 'nvOpticalFlowD3D12.h')) { $NvOfSdk = $candidate }
}
if (-not $NvOfSdk -or -not (Test-Path -LiteralPath (Join-Path $NvOfSdk 'nvOpticalFlowD3D12.h'))) {
    throw 'NVIDIA Optical Flow SDK D3D12 headers not found. Pass -NvOfSdk or set NVOF_SDK.'
}
$fxc = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Recurse -Filter fxc.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\fxc\.exe$' } | Select-Object -First 1
if (-not $fxc) { throw 'Windows SDK fxc.exe not found' }
$shader = Join-Path $PSScriptRoot 'flow_convert.hlsl'; $cso = Join-Path $Output 'flow_convert.cso'
& $fxc.FullName /nologo /T cs_5_0 /E main /Fo $cso $shader
if ($LASTEXITCODE -ne 0) { throw 'flow conversion shader compilation failed' }
$bytes = [IO.File]::ReadAllBytes($cso); $lines = [Text.StringBuilder]::new()
[void]$lines.AppendLine('#pragma once'); [void]$lines.AppendLine('static const unsigned char kFlowConvertBytecode[] = {')
for ($i=0; $i -lt $bytes.Length; $i += 16) { $end = [Math]::Min($i + 16, $bytes.Length); $values = ($i..($end-1) | ForEach-Object { '0x{0:X2}' -f $bytes[$_] }) -join ', '; [void]$lines.AppendLine("    $values,") }
[void]$lines.AppendLine('};'); [void]$lines.AppendLine('static const unsigned int kFlowConvertBytecodeSize = sizeof(kFlowConvertBytecode);')
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'flow_convert_bytecode.h'), $lines.ToString(), [Text.UTF8Encoding]::new($false))
cl /nologo /std:c++17 /O2 /EHsc /W4 /Zi /MD /I"$inc" /I"$NvApi" /I"$NvOfSdk" /Fe:"$Output\dlssg_sm86_offline.exe" "$PSScriptRoot\dlssg_sm86_offline.cpp" "$PSScriptRoot\resource_pipeline.cpp" "$PSScriptRoot\community_run2x.cpp" "$PSScriptRoot\nvof_d3d12.cpp" /link /DEBUG /LIBPATH:"$lib" nvsdk_ngx_d.lib d3d12.lib dxgi.lib version.lib advapi32.lib user32.lib bcrypt.lib
