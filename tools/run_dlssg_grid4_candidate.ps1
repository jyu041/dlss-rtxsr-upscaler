param(
    [Parameter(Mandatory=$true)]
    [Alias('Input')]
    [string]$InputPath,
    [string]$Output,
    [string]$NgxSdk = $env:NVE_NGX_SDK,
    [string]$NvApi = $env:NVE_NVAPI_SDK,
    [string]$NvOfSdk = $env:NVOF_SDK,
    [string]$CommunityRuntime,
    [string]$OfficialRuntimeDir
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Output) {
    $Output = Join-Path $root 'runtime\audit\dlssg-grid4-candidate.mp4'
}
if (-not $CommunityRuntime) {
    $CommunityRuntime = Join-Path $root 'runtime\dlssg\legacy\version.dll'
}
if (-not $OfficialRuntimeDir) {
    $OfficialRuntimeDir = Join-Path $root 'runtime\dlssg\official'
}

$inputResolved = (Resolve-Path -LiteralPath $InputPath).Path
$outputPath = [IO.Path]::GetFullPath($Output)
$outputDir = [IO.Path]::GetDirectoryName($outputPath)
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$build = Join-Path $PSScriptRoot 'build_validate_dlssg_instrumented.ps1'
$worker = Join-Path $root 'native\dlssg_sm86_offline\bin-instrumented\dlssg_sm86_offline.exe'
$video = Join-Path $PSScriptRoot 'dlssg_video.py'
$community = (Resolve-Path -LiteralPath $CommunityRuntime).Path
$official = (Resolve-Path -LiteralPath $OfficialRuntimeDir).Path
$python = (Get-Command python -ErrorAction Stop).Source

$buildArgs = @{
    NgxSdk = $NgxSdk
    NvApi = $NvApi
    NvOfSdk = $NvOfSdk
    CommunityRuntime = $community
    OfficialRuntimeDir = $official
}

Write-Host 'DLSSG_GRID4_CANDIDATE_BUILD_START'
& $build @buildArgs
if ($LASTEXITCODE -ne 0) {
    throw "Grid4 candidate worker build/selftest failed: $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) {
    throw "Instrumented candidate worker missing: $worker"
}
$productionC55 = 'C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916'
$workerHash = (Get-FileHash -LiteralPath $worker -Algorithm SHA256).Hash.ToUpperInvariant()
if ($workerHash -eq $productionC55) {
    throw 'Grid4 candidate gate refuses the pinned production C55 worker identity.'
}

Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue

Write-Host "DLSSG_GRID4_CANDIDATE_RENDER_START input=$inputResolved"
& $python $video `
    --input $inputResolved `
    --output $outputPath `
    --worker $worker `
    --community-runtime $community `
    --official-runtime-dir $official `
    --codec h264_nvenc `
    --multiplier 2 `
    --nvof-profile grid4-gpu-candidate `
    --terminal-frame-policy duplicate `
    --quiet-worker-log
if ($LASTEXITCODE -ne 0) {
    throw "Grid4 candidate real-video render failed: $LASTEXITCODE"
}

$base = Join-Path ([IO.Path]::GetDirectoryName($outputPath)) ([IO.Path]::GetFileNameWithoutExtension($outputPath))
$manifest = "$base.dlssg-manifest.json"
$workerLog = "$base.dlssg-worker.log"
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    throw "Grid4 candidate manifest missing: $manifest"
}
if (-not (Test-Path -LiteralPath $workerLog -PathType Leaf)) {
    throw "Grid4 candidate worker log missing: $workerLog"
}

$report = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
if ($report.status -ne 'PASS') { throw "Grid4 candidate manifest status is $($report.status)" }
if ($report.nvof_profile -ne 'grid4-gpu-candidate') {
    throw "Grid4 candidate manifest profile mismatch: $($report.nvof_profile)"
}
if ([int]$report.multiplier -ne 2) { throw "Grid4 candidate gate expected 2X, got $($report.multiplier)X" }
if (@($report.interpolation_disabled_frame_ids).Count -ne 0) {
    throw 'Grid4 candidate render reported interpolation-disabled frames.'
}
if (@($report.lifecycle_timing_seconds.device_removal_results).Count -ne 0) {
    throw 'Grid4 candidate render reported a device-removal result.'
}
$gridMarker = Select-String -LiteralPath $workerLog -SimpleMatch 'NVOF_OUTPUT_GRID_SELECTED=4 ' -Quiet
if (-not $gridMarker) {
    throw 'Grid4 candidate worker log did not confirm NVOF output grid 4.'
}

Write-Host "DLSSG_GRID4_CANDIDATE_PASS worker_sha256=$workerHash"
Write-Host "DLSSG_GRID4_CANDIDATE_EVIDENCE manifest=$manifest log=$workerLog output=$outputPath"
