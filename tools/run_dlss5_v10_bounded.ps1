param(
    [switch]$Execute,
    [string]$Archive,
    [ValidateRange(0, 15)]
    [int]$GpuOrdinal = 0,
    [string]$Output
)

$ErrorActionPreference = 'Stop'

if (-not $Execute) {
    throw "Bounded DLSS5 v10 native execution is blocked unless -Execute is supplied explicitly."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Archive) {
    $Archive = Join-Path $root 'runtime\downloads\Visual.Enhancer.v10.0.zip'
}
if (-not $Output) {
    $Output = Join-Path $root 'runtime\audit\dlss5-v10-bounded-hardware.json'
}

$python = (Get-Command python -ErrorAction Stop).Source
$archivePath = [System.IO.Path]::GetFullPath($Archive)
$audit = Join-Path $PSScriptRoot 'audit_dlss5_v10.ps1'
$prepare = Join-Path $PSScriptRoot 'prepare_dlss5_v10_candidate.py'
$validate = Join-Path $PSScriptRoot 'validate_dlss5_v10_bounded.py'
$runtime = Join-Path $root 'runtime\dlss5\neuroframe-v10-candidate\bin\runtime\dlssnr'
$preflight = Join-Path $root 'runtime\audit\dlss5-v10-preflight.json'
$outputPath = [System.IO.Path]::GetFullPath($Output)

Write-Host "DLSS5_V10_ARCHIVE_START archive=$archivePath"
& $audit -Archive $archivePath
if ($LASTEXITCODE -ne 0) {
    throw "DLSS5 v10 archive download/static audit failed: $LASTEXITCODE"
}

Write-Host "DLSS5_V10_PREFLIGHT_START archive=$archivePath"
& $python $prepare --archive $archivePath
if ($LASTEXITCODE -ne 0) {
    throw "DLSS5 v10 candidate preparation/Defender preflight failed: $LASTEXITCODE"
}

Write-Host "DLSS5_V10_BOUNDED_START gpu=$GpuOrdinal"
& $python $validate `
    --runtime $runtime `
    --preflight $preflight `
    --output $outputPath `
    --gpu-ordinal $GpuOrdinal `
    --execute `
    --ack BOUNDED_256_ONE_FRAME
if ($LASTEXITCODE -ne 0) {
    throw "DLSS5 v10 bounded hardware gate failed: $LASTEXITCODE"
}

Write-Host "DLSS5_V10_BOUNDED_PASS evidence=$outputPath"
