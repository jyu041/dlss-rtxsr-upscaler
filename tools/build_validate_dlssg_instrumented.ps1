param(
    [string]$NgxSdk = 'C:\Users\mark\AppData\Local\Temp\dlssg-phase3-research\DLSS',
    [string]$NvApi = 'C:\Users\mark\Desktop\dlss-community-research\renodx\external\NVAPI',
    [string]$NvOfSdk = $env:NVOF_SDK,
    [string]$CommunityRuntime = "$PSScriptRoot\..\runtime\dlssg\legacy\version.dll",
    [string]$OfficialRuntimeDir = "$PSScriptRoot\..\runtime\dlssg\official",
    [string]$Evidence = "$PSScriptRoot\..\runtime\audit\mfg-instrumented-validation.json",
    [string]$PracticalEvidence = "$PSScriptRoot\..\runtime\audit\mfg-instrumented-practical-validation.json",
    [switch]$Validate256,
    [switch]$ValidatePractical,
    [switch]$ValidatePracticalGrid4
)

$ErrorActionPreference = 'Stop'
$matrixSwitches = @($Validate256, $ValidatePractical, $ValidatePracticalGrid4) | Where-Object { $_ }
if ($matrixSwitches.Count -gt 1) {
    throw 'Choose only one GPU validation matrix: -Validate256, -ValidatePractical, or -ValidatePracticalGrid4.'
}
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$native = Join-Path $root 'native\dlssg_sm86_offline'
$output = Join-Path $native 'bin-instrumented'
$validatedOutput = Join-Path $native 'bin'
$worker = Join-Path $output 'dlssg_sm86_offline.exe'
$build = Join-Path $native 'build.ps1'

$expectedLegacy = 'C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2'
$expectedProvider = 'FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82'
$productionC55 = 'C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916'

$community = (Resolve-Path -LiteralPath $CommunityRuntime).Path
$official = (Resolve-Path -LiteralPath $OfficialRuntimeDir).Path
$provider = Join-Path $official 'nvngx_dlssg.dll'
if (-not (Test-Path -LiteralPath $provider -PathType Leaf)) {
    throw "Pinned NVIDIA provider missing: $provider"
}

$legacyHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $community).Hash.ToUpperInvariant()
$providerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $provider).Hash.ToUpperInvariant()
if ($legacyHash -ne $expectedLegacy) { throw "Legacy runtime identity mismatch: $legacyHash" }
if ($providerHash -ne $expectedProvider) { throw "Official provider identity mismatch: $providerHash" }

$resolvedOutput = [IO.Path]::GetFullPath($output)
$resolvedValidated = [IO.Path]::GetFullPath($validatedOutput)
if ($resolvedOutput.TrimEnd('\') -eq $resolvedValidated.TrimEnd('\')) {
    throw 'Instrumented output must not equal the validated worker directory.'
}

& $build -NgxSdk $NgxSdk -NvApi $NvApi -NvOfSdk $NvOfSdk -Output $output
if ($LASTEXITCODE -ne 0) { throw "Instrumented worker build failed: $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) {
    throw "Instrumented worker not produced: $worker"
}

# Windows PowerShell 5.1 wraps native stderr as ErrorRecord objects and, with
# $ErrorActionPreference='Stop', can terminate on an otherwise-successful
# diagnostic trace. The worker intentionally writes its self-test stages to
# stderr, so capture both streams through Start-Process and judge success from
# the real process exit code plus the required completion marker.
$selftestStdout = Join-Path $output 'selftest.stdout.txt'
$selftestStderr = Join-Path $output 'selftest.stderr.txt'
Remove-Item -LiteralPath $selftestStdout,$selftestStderr -Force -ErrorAction SilentlyContinue
$selftestProcess = Start-Process -FilePath $worker -ArgumentList '--selftest' -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput $selftestStdout -RedirectStandardError $selftestStderr
$selftestCode = $selftestProcess.ExitCode
$selftestOutput = @()
if (Test-Path -LiteralPath $selftestStdout) { $selftestOutput += @(Get-Content -LiteralPath $selftestStdout) }
if (Test-Path -LiteralPath $selftestStderr) { $selftestOutput += @(Get-Content -LiteralPath $selftestStderr) }
Remove-Item -LiteralPath $selftestStdout,$selftestStderr -Force -ErrorAction SilentlyContinue
if ($selftestCode -ne 0 -or (($selftestOutput -join "\n") -notmatch 'SELFTEST_COMPLETE')) {
    throw "Instrumented worker selftest failed ($selftestCode): $($selftestOutput -join ' | ')"
}

$workerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $worker).Hash.ToUpperInvariant()
if ($workerHash -eq $productionC55) {
    throw 'Build produced the pinned production C55 identity; expected an instrumented development build.'
}

Write-Host "BUILD_PASS worker=$worker"
Write-Host "WORKER_SHA256=$workerHash"
Write-Host 'SELFTEST_PASS'

if (-not $Validate256 -and -not $ValidatePractical -and -not $ValidatePracticalGrid4) {
    Write-Host 'GPU_VALIDATION_SKIPPED: pass -Validate256, -ValidatePractical, or -ValidatePracticalGrid4 explicitly.'
    exit 0
}

$python = Get-Command python -ErrorAction Stop
$validator = Join-Path $root 'tools\validate_dlssg_instrumented.py'
if ($ValidatePracticalGrid4) {
    $matrix = 'practical-grid4'
    $validationEvidence = [IO.Path]::ChangeExtension($PracticalEvidence, $null) + '-grid4.json'
} elseif ($ValidatePractical) {
    $matrix = 'practical'
    $validationEvidence = $PracticalEvidence
} else {
    $matrix = 'bounded'
    $validationEvidence = $Evidence
}
$validatorArgs = @(
    $validator,
    '--worker', $worker,
    '--runtime', $community,
    '--official', $official,
    '--matrix', $matrix,
    '--output', $validationEvidence
)
& $python.Source @validatorArgs
if ($LASTEXITCODE -ne 0) { throw "Instrumented $matrix validation failed: $LASTEXITCODE" }
Write-Host "VALIDATION_PASS matrix=$matrix evidence=$validationEvidence"
