param(
    [Parameter(Mandatory=$true)][string]$Worker,
    [Parameter(Mandatory=$true)][string]$NgxLicense,
    [Parameter(Mandatory=$true)][string]$NvApiHeader,
    [Parameter(Mandatory=$true)][string]$NvOfCommon,
    [Parameter(Mandatory=$true)][string]$NvOfD3D12,
    [Parameter(Mandatory=$true)][string]$OutputDir
)
$ErrorActionPreference = 'Stop'

$workerPath = (Resolve-Path -LiteralPath $Worker).Path
$licensePath = (Resolve-Path -LiteralPath $NgxLicense).Path
$nvapiPath = (Resolve-Path -LiteralPath $NvApiHeader).Path
$nvofCommonPath = (Resolve-Path -LiteralPath $NvOfCommon).Path
$nvofD3d12Path = (Resolve-Path -LiteralPath $NvOfD3D12).Path
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$notices = Join-Path $root 'THIRD_PARTY_NOTICES.md'
if (-not (Test-Path -LiteralPath $notices -PathType Leaf)) { throw "Missing $notices" }

$c55 = 'C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916'
$workerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $workerPath).Hash
if ($workerHash -eq $c55) {
    throw 'Grid4 candidate package refuses the pinned production C55 worker.'
}

& $workerPath --selftest
if ($LASTEXITCODE -ne 0) {
    throw "Grid4 worker selftest failed with exit code $LASTEXITCODE"
}

$out = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse -Force }
New-Item -ItemType Directory -Force -Path $out | Out-Null
$stage = Join-Path $out 'dlssg-grid4-worker'
New-Item -ItemType Directory -Force -Path $stage | Out-Null

Copy-Item -LiteralPath $workerPath -Destination (Join-Path $stage 'dlssg_sm86_offline.exe')
Copy-Item -LiteralPath $licensePath -Destination (Join-Path $stage 'LICENSE-NVIDIA-RTX-SDK.txt')
Copy-Item -LiteralPath $notices -Destination (Join-Path $stage 'THIRD_PARTY_NOTICES.md')

$provenance = [ordered]@{
    schema = 1
    component = 'dlssg-grid4-worker'
    source_commit = $env:GITHUB_SHA
    worker = [ordered]@{
        filename = 'dlssg_sm86_offline.exe'
        size_bytes = (Get-Item -LiteralPath $workerPath).Length
        sha256 = $workerHash
        c55_identity_rejected = $true
    }
    dependencies = [ordered]@{
        nvidia_dlss = [ordered]@{
            repository = 'https://github.com/NVIDIA/DLSS'
            commit = '374959484e79a640feaba44c93ac8cfb0a03f5b5'
            license_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $licensePath).Hash
        }
        nvapi = [ordered]@{
            repository = 'https://github.com/NVIDIA/nvapi'
            commit = '87dca625e83fd89a983e19b904e5f3a580da90d2'
            nvapi_h_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $nvapiPath).Hash
        }
        optical_flow_headers = [ordered]@{
            repository = 'https://github.com/mbucchia/Optical-Flow-SDK'
            commit = '54e68293b4898a530bc07e4d7df71efbc5d30f9b'
            common_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $nvofCommonPath).Hash
            d3d12_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $nvofD3d12Path).Hash
        }
    }
    distribution = [ordered]@{
        project_owned_host = $true
        nvof_runtime_bundled = $false
        nvapi_runtime_bundled = $false
        external_dlssg_runtime_bundled = $false
        official_dlssg_provider_bundled = $false
    }
}
$provenance | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stage 'BUILD-PROVENANCE.json') -Encoding utf8

$archive = Join-Path $out 'dlssg-grid4-worker-candidate.zip'
Compress-Archive -LiteralPath $stage -DestinationPath $archive -CompressionLevel Optimal -Force
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
$summary = [ordered]@{
    worker_sha256 = $workerHash
    worker_size_bytes = (Get-Item -LiteralPath $workerPath).Length
    archive_sha256 = $archiveHash
    archive_size_bytes = (Get-Item -LiteralPath $archive).Length
    archive = $archive
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $out 'grid4-worker-package.json') -Encoding utf8
Write-Host "GRID4_WORKER_PACKAGE_PASS worker_sha256=$workerHash archive_sha256=$archiveHash archive=$archive"
