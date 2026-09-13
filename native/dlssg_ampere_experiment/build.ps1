param([string]$NgxSdk = $(Join-Path $env:TEMP 'dlssg-phase3-research\DLSS'), [string]$Output = $(Join-Path $PSScriptRoot 'bin'))
$ErrorActionPreference='Stop'
$vswhere='C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
$vs=& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if(-not $vs){throw 'Visual Studio C++ Build Tools not found'}
New-Item -ItemType Directory -Force $Output | Out-Null
$vc=Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
$envLines=cmd /s /c "call `"$vc`" && set"
foreach($line in $envLines){$pair=$line -split '=',2;if($pair.Count -eq 2 -and $pair[0] -in @('INCLUDE','LIB','PATH')){Set-Item "Env:$($pair[0])" $pair[1]}}
$inc=Join-Path $NgxSdk 'include'; $lib=Join-Path $NgxSdk 'lib\Windows_x86_64\x64'
$worker=Join-Path $Output 'dlssg_ampere_experiment.exe'; $tests=Join-Path $Output 'bridge_policy_tests.exe'; $probe=Join-Path $Output 'nvapi_prologue_probe.exe'; $providerTests=Join-Path $Output 'provider_transaction_tests.exe'
cl /nologo /std:c++17 /O2 /EHsc /W4 /analyze /MD /I"$inc" /Fe:"$worker" "$PSScriptRoot\dlssg_ampere_experiment.cpp" "$PSScriptRoot\ampere_provider.cpp" "$PSScriptRoot\provider_transaction.cpp" "$PSScriptRoot\ampere_bridge.cpp" /link /LIBPATH:"$lib" nvsdk_ngx_d.lib d3d12.lib dxgi.lib version.lib bcrypt.lib advapi32.lib user32.lib psapi.lib
if($LASTEXITCODE){throw "worker build failed: $LASTEXITCODE"}
cl /nologo /std:c++17 /O2 /EHsc /W4 /analyze /MD /I"$inc" /Fe:"$tests" "$PSScriptRoot\bridge_policy_tests.cpp" "$PSScriptRoot\ampere_bridge.cpp" "$PSScriptRoot\ampere_provider.cpp" "$PSScriptRoot\provider_transaction.cpp" /link bcrypt.lib version.lib kernel32.lib psapi.lib
if($LASTEXITCODE){throw "policy test build failed: $LASTEXITCODE"}
cl /nologo /std:c++17 /O2 /EHsc /W4 /analyze /DAMPERE_PROVIDER_TESTING /MD /I"$inc" /Fe:"$providerTests" "$PSScriptRoot\provider_transaction_tests.cpp" "$PSScriptRoot\ampere_provider.cpp" "$PSScriptRoot\provider_transaction.cpp" /link bcrypt.lib version.lib kernel32.lib psapi.lib
if($LASTEXITCODE){throw "provider transaction test build failed: $LASTEXITCODE"}
cl /nologo /std:c++17 /O2 /EHsc /W4 /analyze /MD /Fe:"$probe" "$PSScriptRoot\nvapi_prologue_probe.cpp" /link bcrypt.lib version.lib kernel32.lib
if($LASTEXITCODE){throw "NVAPI probe build failed: $LASTEXITCODE"}
