param(
    [Parameter(Mandatory=$true)]
    [Alias('Input')]
    [string]$InputPath,
    [Parameter(Mandatory=$true)]
    [string]$CandidateArchive,
    [string]$Output,
    [string]$CommunityRuntime,
    [string]$OfficialRuntimeDir
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$expectedArchiveSize = 209002
$expectedArchiveSha256 = '5A6644CC78EFEFB3705C80E7859D53C0E75081AAAE33C676D0DC451BE74B80C9'
$expectedWorkerSize = 613376
$expectedWorkerSha256 = 'E097BC87558D6E12ECE1963E67CD7330570BCFBF6C6ED336B10F1EF6DF2A5881'
$expectedLicenseSha256 = '3027F23CA5A46DD9CB8183FBD522983A86F64D7DAAC5982912BF9F214671F294'

$archive = (Resolve-Path -LiteralPath $CandidateArchive).Path
$inputResolved = (Resolve-Path -LiteralPath $InputPath).Path
if ((Get-Item -LiteralPath $archive).Length -ne $expectedArchiveSize) {
    throw 'Grid4 candidate archive size mismatch.'
}
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToUpperInvariant()
if ($archiveHash -ne $expectedArchiveSha256) {
    throw "Grid4 candidate archive identity mismatch: $archiveHash"
}

if (-not $CommunityRuntime) {
    $CommunityRuntime = Join-Path $root 'runtime\dlssg\legacy\version.dll'
}
if (-not $OfficialRuntimeDir) {
    $OfficialRuntimeDir = Join-Path $root 'runtime\dlssg\official'
}
$community = (Resolve-Path -LiteralPath $CommunityRuntime).Path
$official = (Resolve-Path -LiteralPath $OfficialRuntimeDir).Path
if (-not $Output) {
    $Output = Join-Path $root 'runtime\audit\dlssg-grid4-managed-candidate.mp4'
}
$outputPath = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($outputPath)) | Out-Null

$stage = Join-Path $root ('runtime\audit\grid4-stage-' + [Guid]::NewGuid().ToString('N'))
$managedDir = Join-Path $root 'runtime\dlssg\grid4-worker'
$managedWorker = Join-Path $managedDir 'dlssg_sm86_offline.exe'
try {
    Expand-Archive -LiteralPath $archive -DestinationPath $stage
    $payload = Join-Path $stage 'dlssg-grid4-worker'
    $candidateWorker = Join-Path $payload 'dlssg_sm86_offline.exe'
    $candidateLicense = Join-Path $payload 'LICENSE-NVIDIA-RTX-SDK.txt'
    $candidateProvenance = Join-Path $payload 'BUILD-PROVENANCE.json'
    foreach ($required in @($candidateWorker, $candidateLicense, $candidateProvenance)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Grid4 candidate archive is missing required file: $required"
        }
    }
    if ((Get-Item -LiteralPath $candidateWorker).Length -ne $expectedWorkerSize) {
        throw 'Grid4 candidate worker size mismatch.'
    }
    $workerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidateWorker).Hash.ToUpperInvariant()
    if ($workerHash -ne $expectedWorkerSha256) {
        throw "Grid4 candidate worker identity mismatch: $workerHash"
    }
    $licenseHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidateLicense).Hash.ToUpperInvariant()
    if ($licenseHash -ne $expectedLicenseSha256) {
        throw "Grid4 candidate NVIDIA license identity mismatch: $licenseHash"
    }
    $provenance = Get-Content -LiteralPath $candidateProvenance -Raw | ConvertFrom-Json
    if ($provenance.worker.sha256 -ne $expectedWorkerSha256) {
        throw 'Grid4 candidate provenance worker identity mismatch.'
    }

    if (Test-Path -LiteralPath $managedDir) {
        Remove-Item -LiteralPath $managedDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $managedDir | Out-Null
    Copy-Item -Path (Join-Path $payload '*') -Destination $managedDir -Recurse -Force

    Write-Host "DLSSG_GRID4_MANAGED_SELFTEST_START worker=$managedWorker"
    & $managedWorker --selftest
    if ($LASTEXITCODE -ne 0) {
        throw "Managed grid4 worker selftest failed: $LASTEXITCODE"
    }

    $python = (Get-Command python -ErrorAction Stop).Source
    $video = Join-Path $PSScriptRoot 'dlssg_video.py'
    Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue
    Write-Host "DLSSG_GRID4_MANAGED_RENDER_START input=$inputResolved"
    & $python $video `
        --input $inputResolved `
        --output $outputPath `
        --worker $managedWorker `
        --community-runtime $community `
        --official-runtime-dir $official `
        --codec h264_nvenc `
        --multiplier 2 `
        --nvof-profile grid4-gpu-candidate `
        --terminal-frame-policy duplicate `
        --quiet-worker-log
    if ($LASTEXITCODE -ne 0) {
        throw "Managed grid4 candidate real-video render failed: $LASTEXITCODE"
    }

    $base = Join-Path ([IO.Path]::GetDirectoryName($outputPath)) ([IO.Path]::GetFileNameWithoutExtension($outputPath))
    $manifest = "$base.dlssg-manifest.json"
    $workerLog = "$base.dlssg-worker.log"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Missing render manifest: $manifest" }
    if (-not (Test-Path -LiteralPath $workerLog -PathType Leaf)) { throw "Missing worker log: $workerLog" }
    $report = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    if ($report.status -ne 'PASS') { throw "Grid4 candidate manifest status is $($report.status)" }
    if ($report.nvof_profile -ne 'grid4-gpu-candidate') { throw 'Grid4 candidate profile mismatch.' }
    if ([int]$report.multiplier -ne 2) { throw 'Grid4 managed gate requires 2X.' }
    if (@($report.interpolation_disabled_frame_ids).Count -ne 0) {
        throw 'Grid4 candidate render reported interpolation-disabled frames.'
    }
    if (@($report.lifecycle_timing_seconds.device_removal_results).Count -ne 0) {
        throw 'Grid4 candidate render reported a device-removal result.'
    }
    if (-not (Select-String -LiteralPath $workerLog -SimpleMatch 'NVOF_OUTPUT_GRID_SELECTED=4 ' -Quiet)) {
        throw 'Grid4 candidate worker log did not confirm output grid 4.'
    }

    Write-Host "DLSSG_GRID4_MANAGED_CANDIDATE_PASS worker_sha256=$workerHash archive_sha256=$archiveHash"
    Write-Host "DLSSG_GRID4_MANAGED_CANDIDATE_EVIDENCE manifest=$manifest log=$workerLog output=$outputPath"
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}
