[CmdletBinding()]
param([string]$Root = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)))

$ErrorActionPreference = 'Stop'
$rootPath = [IO.Path]::GetFullPath($Root)
$metadataPath = Join-Path $rootPath 'tools\portable_toolchain.json'
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    Write-Error "Portable toolchain metadata is missing: $metadataPath"
    exit 1
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
$cache = Join-Path $rootPath '.cache\portable'
New-Item -ItemType Directory -Force -Path $cache | Out-Null

function Get-Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant() }
function Get-Verified([string]$Url, [string]$Name, [Int64]$Size, [string]$Hash) {
    if ($Url -notlike 'https://*') { throw "Refusing non-HTTPS source: $Url" }
    $target = Join-Path $cache $Name
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        $item = Get-Item -LiteralPath $target
        if ($item.Length -ne $Size -or (Get-Sha256 $target) -ne $Hash) { Remove-Item -LiteralPath $target -Force }
    }
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        Write-Host "Downloading pinned artifact $Name"
        Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing
    }
    $item = Get-Item -LiteralPath $target
    if ($item.Length -ne $Size -or (Get-Sha256 $target) -ne $Hash) { throw "Pinned artifact verification failed: $Name" }
    return $target
}

$missing = @(
    (Join-Path $rootPath 'runtime\python\python.exe'),
    (Join-Path $rootPath 'runtime\tools\ffmpeg\ffmpeg.exe'),
    (Join-Path $rootPath 'runtime\tools\ffmpeg\ffprobe.exe')
) | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }
if ($missing.Count -eq 0) {
    Write-Host 'Portable base files are present. Run start.bat or check_portable_runtime.py.'
    exit 0
}
Write-Host 'Portable runtime requires repair.'
Write-Host 'This repair script only uses pinned HTTPS artifacts and never substitutes system Python, Conda, or FFmpeg.'
Write-Host ('Missing: ' + ($missing -join ', '))
Write-Host ('Pinned Python: ' + $metadata.python.archive)
Write-Host ('Pinned FFmpeg: ' + $metadata.ffmpeg.archive)
Write-Host 'A complete dependency lock and licensed runtime staging input are required before automatic reconstruction is enabled.'
exit 2
