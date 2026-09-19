param(
    [switch]$Execute,
    [Parameter(Mandatory=$true)]
    [Alias('Input')]
    [string]$InputPath,
    [ValidateRange(0, 100000000)]
    [int]$StartFrame = 30,
    [string]$Archive,
    [ValidateRange(0, 15)]
    [int]$GpuOrdinal = 0,
    [string]$Output
)

$ErrorActionPreference = 'Stop'

if (-not $Execute) {
    throw "Bounded DLSS5 v10 real-video A/B execution is blocked unless -Execute is supplied explicitly."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$inputResolved = (Resolve-Path -LiteralPath $InputPath).Path
if (-not $Archive) {
    $Archive = Join-Path $root 'runtime\downloads\Visual.Enhancer.v10.0.zip'
}
if (-not $Output) {
    $Output = Join-Path $root 'runtime\audit\dlss5-v10-video-ab-hardware.json'
}

$python = (Get-Command python -ErrorAction Stop).Source
$archivePath = [System.IO.Path]::GetFullPath($Archive)
$audit = Join-Path $PSScriptRoot 'audit_dlss5_v10.ps1'
$prepare = Join-Path $PSScriptRoot 'prepare_dlss5_v10_candidate.py'
$validate = Join-Path $PSScriptRoot 'validate_dlss5_v10_video_ab.py'
$runtime = Join-Path $root 'runtime\dlss5\neuroframe-v10-candidate\bin\runtime\dlssnr'
$preflight = Join-Path $root 'runtime\audit\dlss5-v10-preflight.json'
$outputPath = [System.IO.Path]::GetFullPath($Output)

Write-Host "DLSS5_V10_VIDEO_AB_ARCHIVE_START archive=$archivePath"
& $audit -Archive $archivePath
if ($LASTEXITCODE -ne 0) {
    throw "DLSS5 v10 archive download/static audit failed: $LASTEXITCODE"
}

Write-Host "DLSS5_V10_VIDEO_AB_PREFLIGHT_START archive=$archivePath"
& $python $prepare --archive $archivePath
if ($LASTEXITCODE -ne 0) {
    throw "DLSS5 v10 candidate preparation/Defender preflight failed: $LASTEXITCODE"
}

Write-Host "DLSS5_V10_VIDEO_AB_START input=$inputResolved start_frame=$StartFrame gpu=$GpuOrdinal"
& $python $validate `
    --input $inputResolved `
    --runtime $runtime `
    --preflight $preflight `
    --output $outputPath `
    --gpu-ordinal $GpuOrdinal `
    --start-frame $StartFrame `
    --execute `
    --ack BOUNDED_256_VIDEO_AB_16
if ($LASTEXITCODE -ne 0) {
    throw "DLSS5 v10 real-video temporal A/B gate failed: $LASTEXITCODE"
}

Write-Host "DLSS5_V10_VIDEO_AB_PASS evidence=$outputPath"
