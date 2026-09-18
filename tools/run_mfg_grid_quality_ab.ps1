param(
    [Parameter(Mandatory=$true)]
    [Alias('Input')]
    [string]$InputPath,
    [ValidateSet(2,4)]
    [int]$Multiplier = 2,
    [ValidateRange(1,24)]
    [int]$Groups = 8,
    [ValidateRange(0,1000000)]
    [int]$StartFrame = 0,
    [string]$NgxSdk = 'C:\Users\mark\AppData\Local\Temp\dlssg-phase3-research\DLSS',
    [string]$NvApi = '',
    [string]$NvOfSdk = $env:NVOF_SDK,
    [string]$OutputDir = "$PSScriptRoot\..\runtime\quality\mfg-grid-ab"
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$inputPath = (Resolve-Path -LiteralPath $InputPath).Path
$build = Join-Path $PSScriptRoot 'build_validate_dlssg_instrumented.ps1'
$worker = Join-Path $root 'native\dlssg_sm86_offline\bin-instrumented\dlssg_sm86_offline.exe'
$runtime = Join-Path $root 'runtime\dlssg\legacy\version.dll'
$official = Join-Path $root 'runtime\dlssg\official'
$quality = Join-Path $PSScriptRoot 'capture_mfg_grid_quality_ab.py'

$buildArgs = @{
    NgxSdk = $NgxSdk
}
if ($NvApi) { $buildArgs['NvApi'] = $NvApi }
if ($NvOfSdk) { $buildArgs['NvOfSdk'] = $NvOfSdk }

& $build @buildArgs
if ($LASTEXITCODE -ne 0) {
    throw "Instrumented worker build/selftest failed: $LASTEXITCODE"
}

$python = Get-Command python -ErrorAction Stop
$qualityArgs = @(
    $quality,
    '--input', $inputPath,
    '--multiplier', $Multiplier,
    '--groups', $Groups,
    '--start-frame', $StartFrame,
    '--worker', $worker,
    '--runtime', $runtime,
    '--official', $official,
    '--output-dir', $OutputDir
)
& $python.Source @qualityArgs
if ($LASTEXITCODE -ne 0) {
    throw "MFG grid quality A/B failed: $LASTEXITCODE"
}
