param([string]$Output = $(Join-Path $PSScriptRoot 'build'), [string]$NgxRoot = 'C:\Users\mark\Desktop\dlss-community-research\renodx\external\DLSS', [string]$NvapiRoot = 'C:\Users\mark\Desktop\dlss-community-research\renodx\external\NVAPI')
$ErrorActionPreference = 'Stop'
$vswhere = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Visual Studio C++ Build Tools not found' }
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Visual Studio C++ Build Tools not found' }
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
$envLines = cmd /s /c "call `"$vcvars`" && set"
foreach ($line in $envLines) {
    $pair = $line -split '=', 2
    if ($pair.Count -eq 2 -and $pair[0] -in @('INCLUDE','LIB','PATH')) { Set-Item "Env:$($pair[0])" $pair[1] }
}
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$exe = Join-Path $Output 'dlssg_ampere_reference.exe'
$inc = Join-Path $NgxRoot 'include'
$lib = Join-Path $NgxRoot 'lib\Windows_x86_64\x64'
if (-not (Test-Path -LiteralPath $inc)) { throw "NGX SDK include directory not found: $inc" }
if (-not (Test-Path -LiteralPath $lib)) { throw "NGX SDK library directory not found: $lib" }
if (-not (Test-Path -LiteralPath (Join-Path $NvapiRoot 'nvapi.h'))) { throw "NVAPI header directory not found: $NvapiRoot" }
cl /nologo /std:c++17 /O2 /EHsc /W4 /analyze /MD /I"$inc" /I"$NvapiRoot" /Fe:"$exe" "$PSScriptRoot\standalone_host.cpp" "$PSScriptRoot\ampere_provider.cpp" "$PSScriptRoot\provider_transaction.cpp" "$PSScriptRoot\ampere_bridge.cpp" /link /LIBPATH:"$lib" nvsdk_ngx_d.lib d3d12.lib dxgi.lib version.lib bcrypt.lib advapi32.lib user32.lib psapi.lib
if ($LASTEXITCODE) { throw "reference harness build failed: $LASTEXITCODE" }
