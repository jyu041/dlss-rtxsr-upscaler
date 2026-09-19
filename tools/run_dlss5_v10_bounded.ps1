param(
    [switch]$Execute,
    [string]$Archive = "$PSScriptRoot\..\runtime\downloads\Visual.Enhancer.v10.0.zip",
    [ValidateRange(0, 15)]
    [int]$GpuOrdinal = 0,
    [string]$Output = "$PSScriptRoot\..\runtime\audit\dlss5-v10-bounded-hardware.json"
)

$ErrorActionPreference = 'Stop'

if (-not $Execute) {
    throw "Bounded DLSS5 v10 native execution is blocked unless -Execute is supplied explicitly."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = (Get-Command python -ErrorAction Stop).Source
$archivePath = (Resolve-Path -LiteralPath $Archive).Path
$prepare = Join-Path $PSScriptRoot 'prepare_dlss5_v10_candidate.py'
$validate = Join-Path $PSScriptRoot 'validate_dlss5_v10_bounded.py'
$runtime = Join-Path $root 'runtime\dlss5\neuroframe-v10-candidate\bin\runtime\dlssnr'
$preflight = Join-Path $root 'runtime\audit\dlss5-v10-preflight.json'
$outputPath = [System.IO.Path]::GetFullPath($Output)

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
