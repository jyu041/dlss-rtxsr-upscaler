param(
    [Parameter(Mandatory = $true)]
    [string]$NgxSdk,
    [string]$Output = (Join-Path $env:TEMP "dlssg-probe\bin")
)

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "dlssg_probe.cpp"
$include = Join-Path $NgxSdk "include"
$library = Join-Path $NgxSdk "lib\Windows_x86_64\x64\nvsdk_ngx_d.lib"
if (-not (Test-Path -LiteralPath $include) -or -not (Test-Path -LiteralPath $library)) { throw "Official NVIDIA DLSS SDK include/lib not found" }
if (-not (Test-Path -LiteralPath $Output)) { New-Item -ItemType Directory -Path $Output -Force | Out-Null }

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "Visual Studio C++ tools not found" }
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
cmd /s /c "`"$vcvars`" && set" | ForEach-Object {
    if ($_ -match "^(INCLUDE|LIB|PATH)=(.*)$") { Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2] }
}

cl /nologo /std:c++17 /O2 /EHsc /W4 /MD /I"$include" /Fe:"$(Join-Path $Output 'dlssg_probe.exe')" "$source" /link /LIBPATH:"$(Split-Path $library)" nvsdk_ngx_d.lib d3d12.lib dxgi.lib version.lib advapi32.lib user32.lib
