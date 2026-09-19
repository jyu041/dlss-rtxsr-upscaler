param(
    [switch]$Execute,
    [Parameter(Mandatory=$true)]
    [Alias('Input')]
    [string]$InputPath,
    [ValidateRange(0, 36000)]
    [double]$Start = 0,
    [ValidateRange(1, 30)]
    [double]$Duration = 3,
    [string]$Archive,
    [string]$Output
)

$ErrorActionPreference = 'Stop'

if (-not $Execute) {
    throw "Experimental DLSS5 v10 application smoke execution is blocked unless -Execute is supplied explicitly."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$inputResolved = (Resolve-Path -LiteralPath $InputPath).Path
if (-not $Archive) {
    $Archive = Join-Path $root 'runtime\downloads\Visual.Enhancer.v10.0.zip'
}
if (-not $Output) {
    $Output = Join-Path $root 'runtime\audit\dlss5-v10-app-smoke.mp4'
}

$python = (Get-Command python -ErrorAction Stop).Source
$archivePath = [System.IO.Path]::GetFullPath($Archive)
$outputPath = [System.IO.Path]::GetFullPath($Output)
$audit = Join-Path $PSScriptRoot 'audit_dlss5_v10.ps1'
$prepare = Join-Path $PSScriptRoot 'prepare_dlss5_v10_candidate.py'
$render = Join-Path $PSScriptRoot 'dlss5_v10_video.py'

Write-Host "DLSS5_V10_APP_SMOKE_ARCHIVE_START archive=$archivePath"
& $audit -Archive $archivePath
if ($LASTEXITCODE -ne 0) {
    throw "DLSS5 v10 archive download/static audit failed: $LASTEXITCODE"
}

Write-Host "DLSS5_V10_APP_SMOKE_PREFLIGHT_START archive=$archivePath"
& $python $prepare --archive $archivePath
if ($LASTEXITCODE -ne 0) {
    throw "DLSS5 v10 candidate preparation/Defender preflight failed: $LASTEXITCODE"
}

Write-Host "DLSS5_V10_APP_SMOKE_RENDER_START input=$inputResolved start=$Start duration=$Duration"
& $python $render `
    --input $inputResolved `
    --output $outputPath `
    --start $Start `
    --duration $Duration `
    --execute `
    --ack EXPERIMENTAL_APP_SCENE_AWARE_V10
if ($LASTEXITCODE -ne 0) {
    throw "DLSS5 v10 experimental application smoke render failed: $LASTEXITCODE"
}

Write-Host "DLSS5_V10_APP_SMOKE_PASS output=$outputPath"
