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
$missing = @($missing)
if ($missing.Count -eq 0) {
    Write-Host 'Portable base files are present. Running full verification.'
    $python = Join-Path $rootPath 'runtime\python\python.exe'
    if (Test-Path -LiteralPath (Join-Path $rootPath 'tools\check_portable_runtime.py')) {
        & $python (Join-Path $rootPath 'tools\check_portable_runtime.py') --root $rootPath --full
        if ($LASTEXITCODE -eq 0) { exit 0 }
        Write-Host 'Full verification failed; reconstructing the runtime from the pinned lock.'
    }
}
Write-Host 'Portable runtime requires repair.'
Write-Host 'This repair script only uses pinned HTTPS artifacts and never substitutes system Python, Conda, or FFmpeg.'
Write-Host ('Missing: ' + ($missing -join ', '))
if ($env:NVE_REPAIR_APPROVED -ne '1') {
    $answer = Read-Host 'Download and reconstruct from the pinned artifacts now? [y/N]'
    if ($answer -notmatch '^(y|yes)$') { Write-Host 'Repair cancelled before download.'; exit 3 }
}
$pyArchive = Get-Verified $metadata.python.url $metadata.python.archive ([Int64]$metadata.python.size_bytes) $metadata.python.sha256
$ffArchive = Get-Verified $metadata.ffmpeg.url $metadata.ffmpeg.archive ([Int64]$metadata.ffmpeg.size_bytes) $metadata.ffmpeg.sha256
$lock = Join-Path $rootPath 'tools\portable_runtime_lock.json'
$assembler = Join-Path $rootPath 'tools\assemble_portable_runtime.py'
if (-not (Test-Path -LiteralPath $lock -PathType Leaf) -or -not (Test-Path -LiteralPath $assembler -PathType Leaf)) { throw 'Portable artifact lock or assembler is missing.' }
$wheelDir = Join-Path $cache 'wheels'
$bootstrap = Join-Path $cache 'bootstrap-python'
if (Test-Path -LiteralPath $bootstrap) { Remove-Item -LiteralPath $bootstrap -Recurse -Force }
New-Item -ItemType Directory -Force -Path $bootstrap | Out-Null
Expand-Archive -LiteralPath $pyArchive -DestinationPath $bootstrap -Force
$mode = if ($missing.Count -eq 1 -and ([string]$missing[0]).ToLowerInvariant().Contains('ffmpeg')) { '--ffmpeg-only' } else { '' }
$repairRoot = Join-Path $env:TEMP ('nve-repair-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $repairRoot | Out-Null
if ($mode) {
    $args = @($assembler, '--root', $rootPath, '--python-archive', $pyArchive, '--ffmpeg-archive', $ffArchive, '--wheel-dir', $wheelDir, '--lock', $lock, $mode)
    & (Join-Path $bootstrap 'python.exe') @args
    exit $LASTEXITCODE
}
$stage = Join-Path $repairRoot ('python-new-' + [guid]::NewGuid().ToString('N'))
$args = @($assembler, '--root', $rootPath, '--runtime-root', $stage, '--python-archive', $pyArchive, '--ffmpeg-archive', $ffArchive, '--wheel-dir', $wheelDir, '--lock', $lock)
& (Join-Path $bootstrap 'python.exe') @args
if ($LASTEXITCODE -ne 0) { Write-Error 'Staged Python assembly failed; existing runtime was preserved.'; exit $LASTEXITCODE }
$stagedPython = Join-Path $stage 'python\python.exe'
if (-not (Test-Path -LiteralPath $stagedPython -PathType Leaf)) { Write-Error 'Staged Python executable is missing; existing runtime was preserved.'; exit 1 }
& $stagedPython -c 'import nvvfx, torch; assert torch.__version__ == "2.10.0+cu128"; assert torch.cuda.is_available()'
if ($LASTEXITCODE -ne 0) { Write-Error 'Staged Python critical import/CUDA validation failed; existing runtime was preserved.'; exit $LASTEXITCODE }
$old = Join-Path $rootPath 'runtime\python'; $backup = Join-Path $repairRoot ('python-old-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $old) { Move-Item -LiteralPath $old -Destination $backup }
Move-Item -LiteralPath $stagedPython -Destination $old
$check = Join-Path $rootPath 'tools\check_portable_runtime.py'
& (Join-Path $old 'python.exe') $check --root $rootPath --full
if ($LASTEXITCODE -ne 0) {
    Remove-Item -LiteralPath $old -Recurse -Force
    if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $old }
    Write-Error 'Final verification failed; previous runtime restored.'; exit 1
}
if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
exit 0
