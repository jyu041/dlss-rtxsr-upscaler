param(
    [string]$Archive,
    [string]$Output,
    [switch]$NoDownload
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Archive) {
    $Archive = Join-Path $root 'runtime\downloads\Visual.Enhancer.v10.0.zip'
}
if (-not $Output) {
    $Output = Join-Path $root 'runtime\audit\dlss5-v10-static.json'
}

$archivePath = [IO.Path]::GetFullPath($Archive)
$outputPath = [IO.Path]::GetFullPath($Output)
$url = 'https://github.com/Merserk/dlss5-visual-enhancer/releases/download/v10.0/Visual.Enhancer.v10.0.zip'
$expectedSize = 690203043
$expectedSha256 = '394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515'

function Assert-ArchiveIdentity([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "v10 archive is missing: $Path"
    }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne $expectedSize) {
        throw "v10 archive size mismatch: $($item.Length) != $expectedSize"
    }
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToUpperInvariant()
    if ($digest -ne $expectedSha256) {
        throw "v10 archive SHA-256 mismatch: $digest"
    }
    return $digest
}

if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    if ($NoDownload) {
        throw "v10 archive is absent and -NoDownload was specified: $archivePath"
    }

    $archiveDir = Split-Path -Parent $archivePath
    New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null
    $partial = "$archivePath.part"
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue

    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source --location --fail --retry 3 --retry-delay 2 --output $partial $url
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
            throw "curl download failed with exit code $LASTEXITCODE"
        }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $partial -MaximumRedirection 10
    }

    try {
        Assert-ArchiveIdentity $partial | Out-Null
        Move-Item -LiteralPath $partial -Destination $archivePath -Force
    } catch {
        Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
        throw
    }
}

$digest = Assert-ArchiveIdentity $archivePath
Write-Host "ARCHIVE_IDENTITY_PASS size=$expectedSize sha256=$digest"

$outputDir = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$python = Get-Command python -ErrorAction Stop
$auditor = Join-Path $root 'tools\audit_runtime_candidate.py'
$args = @(
    $auditor,
    'dlss5-neuroframe-v10-static-candidate',
    '--archive', $archivePath,
    '--authenticode',
    '--output', $outputPath
)
& $python.Source @args
if ($LASTEXITCODE -ne 0) {
    throw "v10 static candidate audit failed with exit code $LASTEXITCODE"
}

Write-Host "STATIC_AUDIT_PASS evidence=$outputPath"
Write-Host 'NO_V10_DLL_EXECUTED=1'
