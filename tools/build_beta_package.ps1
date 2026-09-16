param(
    [Parameter(Mandatory=$true)][string]$WorkerPath,
    [Parameter(Mandatory=$true)][string]$DlssSrHostPath,
    [Parameter(Mandatory=$true)][string]$DlssSrRuntimePath,
    [Parameter(Mandatory=$true)][string]$NvidiaSdkLicensePath,
    [Parameter(Mandatory=$true)][string]$SourceCommit,
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$SourceCommit = $SourceCommit.Trim()
$OutputDirectory = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $root 'runtime\beta-package' }
$expected = @{
    Worker = 'C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916'
    Host = 'E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB'
    Runtime = '3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983'
    License = '3027F23CA5A46DD9CB8183FBD522983A86F64D7DAAC5982912BF9F214671F294'
}
function Resolve-Input([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label input is missing: $Path" }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $bytes = [System.IO.File]::ReadAllBytes($resolved)
    $prefix = [System.Text.Encoding]::ASCII.GetString($bytes[0..([Math]::Min(63, $bytes.Length - 1))])
    if ($prefix.StartsWith('version https://git-lfs.github.com/spec/v1')) { throw "$Label input is a Git LFS pointer, not a real file: $resolved" }
    return $resolved
}
function Assert-Hash([string]$Path, [string]$Expected, [string]$Label) {
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actual -ne $Expected) { throw "$Label hash mismatch: $actual" }
    return $actual
}
$actualCommit = (& git -C $root rev-parse HEAD).Trim()
if ($SourceCommit -ne $actualCommit) { throw "Source HEAD $actualCommit does not match requested commit $SourceCommit" }
$worker = Resolve-Input $WorkerPath 'DLSS-G worker'
$srHost = Resolve-Input $DlssSrHostPath 'DLSS SR host'
$runtime = Resolve-Input $DlssSrRuntimePath 'DLSS SR runtime'
$license = Resolve-Input $NvidiaSdkLicensePath 'NVIDIA SDK license'
$workerHash = Assert-Hash $worker $expected.Worker 'DLSS-G worker'
$hostHash = Assert-Hash $srHost $expected.Host 'DLSS SR host'
$runtimeHash = Assert-Hash $runtime $expected.Runtime 'DLSS SR runtime'
$licenseHash = Assert-Hash $license $expected.License 'NVIDIA SDK license'
$packageName = 'NVIDIA-Video-Enhancer-v0.1.0-beta.2'
$outputRoot = (Resolve-Path -LiteralPath (New-Item -ItemType Directory -Force -Path $OutputDirectory)).Path
$stage = Join-Path $outputRoot $packageName
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
$files = @('app.py','environment.yml','requirements.txt','setup.bat','start.bat','LICENSE','README.md','BINARY_DISTRIBUTION_NOTICES.md','THIRD_PARTY_NOTICES.md','docs\INSTALL.md','docs\SECURITY_AUDIT.md','docs\TESTING.md','docs\THIRD_PARTY.md','docs\RELEASE_NOTES_v0.1.0-beta.2.md','tools\check_dlssg_readiness.py','tools\check_dlss_sr_readiness.py')
$files += @(& git -C $root ls-files src config | Where-Object { $_ -notmatch 'settings\.local\.json|user_presets\.json|\.pyc$' })
foreach ($relative in ($files | Select-Object -Unique)) {
    $source = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Required package file missing: $relative" }
    $destination = Join-Path $stage $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
}
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'runtime\dlssg_sm86_offline') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'runtime\dlss-sr-host') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'licenses') | Out-Null
Copy-Item $worker (Join-Path $stage 'runtime\dlssg_sm86_offline\dlssg_sm86_offline.exe')
Copy-Item $srHost (Join-Path $stage 'runtime\dlss-sr-host\dlss_sr_host.exe')
Copy-Item $runtime (Join-Path $stage 'runtime\dlss-sr-host\nvngx_dlss.dll')
Copy-Item $license (Join-Path $stage 'licenses\NVIDIA_RTX_SDK_LICENSE.txt')
$manifest = [ordered]@{ product='NVIDIA Video Enhancer'; package_version='v0.1.0-beta.2'; package_schema_version=2; source_commit=$actualCommit; private_resource_commit='a77abe9643d8c33d2ca05176a77d2920dea91d9d'; validation_scope=@{os='Windows 11 build 26200'; gpu='RTX 3070 Ti 8 GB'; driver='610.62'}; rtx_vsr=@{nvidia_vfx='0.1.0.1'; sdk='1.2.0'; installed_through_setup=$true; bundled_runtime_dlls=$false}; dlss_sr=@{host_bundled=$true; host_sha256=$hostHash; host_ownership='PROJECT_OWNED'; host_authenticode='unsigned'; official_runtime_bundled=$true; runtime_sha256=$runtimeHash; nvidia_file_version='310.9.1.0'; sdk_commit='374959484e79a640feaba44c93ac8cfb0a03f5b5'; license_sha256=$licenseHash; machine_attestation_bundled=$false; first_use_selftest_required=$true}; dlssg=@{c55_bundled=$true; c55_sha256=$workerHash; community_runtime_bundled=$false; official_runtime_bundled=$false}; dlss5=@{experimental=$true; runtime_bundled=$false}; other=@{ffmpeg_bundled=$false; ffprobe_bundled=$false; nvofapi64_bundled=$false; nvapi64_bundled=$false}; notice_filenames=@('LICENSE','docs/THIRD_PARTY.md','BINARY_DISTRIBUTION_NOTICES.md','licenses/NVIDIA_RTX_SDK_LICENSE.txt') }
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stage 'release-manifest.json') -Encoding utf8
$zip = Join-Path $outputRoot "$packageName.zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal
$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToUpperInvariant()
$sums = Join-Path $outputRoot 'SHA256SUMS.txt'
Set-Content -LiteralPath $sums -Value "$zipHash  $packageName.zip" -Encoding ascii
Write-Output "PACKAGE=$zip"; Write-Output "ZIP_SIZE=$((Get-Item $zip).Length)"; Write-Output "ZIP_SHA256=$zipHash"; Write-Output "SHA256SUMS=$sums"
