param(
    [Parameter(Mandatory=$true)][string]$WorkerPath,
    [Parameter(Mandatory=$true)][string]$SourceCommit,
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$SourceCommit = $SourceCommit.Trim()
$OutputDirectory = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $root 'runtime\beta-package' }
$worker = (Resolve-Path -LiteralPath $WorkerPath).Path
$expectedWorkerSha = 'C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916'
$actualCommit = (& git -C $root rev-parse HEAD).Trim()
if ($SourceCommit -ne $actualCommit) { throw "Source HEAD $actualCommit does not match requested commit $SourceCommit" }
$workerHash = (Get-FileHash -LiteralPath $worker -Algorithm SHA256).Hash.ToUpperInvariant()
if ($workerHash -ne $expectedWorkerSha) { throw "Refusing non-production worker: $workerHash" }

$packageName = 'NVIDIA-Video-Enhancer-beta-candidate'
if (-not (Test-Path -LiteralPath $OutputDirectory)) { New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null }
$stage = Join-Path (Resolve-Path -LiteralPath $OutputDirectory).Path $packageName
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$files = @(
    'app.py','environment.yml','requirements.txt','setup.bat','start.bat','LICENSE','README.md',
    'BINARY_DISTRIBUTION_NOTICES.md','THIRD_PARTY_NOTICES.md',
    'docs\INSTALL.md','docs\SECURITY_AUDIT.md','docs\DLSS5_APPROVAL.md',
    'tools\check_dlssg_readiness.py'
)
$files += @(& git -C $root ls-files src config | Where-Object { $_ -notmatch '(^|/)settings\.local\.json$' })
$files = @($files | Select-Object -Unique)
foreach ($relative in $files) {
    $source = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Required package file missing: $relative" }
    $destination = Join-Path $stage $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
}
$workerDestination = Join-Path $stage 'runtime\dlssg_sm86_offline\dlssg_sm86_offline.exe'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $workerDestination) | Out-Null
Copy-Item -LiteralPath $worker -Destination $workerDestination

$manifest = [ordered]@{
    product = 'NVIDIA Video Enhancer'
    package_schema_version = 1
    source_git_commit = $actualCommit
    build_utc = [DateTime]::UtcNow.ToString('o')
    worker_filename = 'runtime/dlssg_sm86_offline/dlssg_sm86_offline.exe'
    worker_sha256 = $workerHash
    worker_protocol_version = 4
    worker_distribution_classification = 'A - PUBLIC REDISTRIBUTION SUPPORTED BY AVAILABLE LICENSE EVIDENCE'
    community_runtime_bundled = $false
    official_nvidia_runtime_bundled = $false
    driver_dlls_bundled = $false
    required_external_dependencies = @('Windows 10/11 x64','NVIDIA driver with nvofapi64.dll','FFmpeg and FFprobe with h264_nvenc/hevc_nvenc','user-supplied community version.dll','user-supplied official NVIDIA NGX runtime directory')
    notice_filenames = @('LICENSE','THIRD_PARTY_NOTICES.md','BINARY_DISTRIBUTION_NOTICES.md')
    hash_note = 'Hashes identify this artifact; they are not a safety guarantee.'
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stage 'release-manifest.json') -Encoding utf8

$zip = Join-Path (Resolve-Path -LiteralPath $OutputDirectory).Path "$packageName.zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal
$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToUpperInvariant()
Set-Content -LiteralPath (Join-Path (Resolve-Path -LiteralPath $OutputDirectory).Path 'SHA256SUMS.txt') -Value "$zipHash  $packageName.zip" -Encoding ascii
Write-Output "PACKAGE=$zip"
Write-Output "ZIP_SHA256=$zipHash"
