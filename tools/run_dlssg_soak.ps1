param(
    [Parameter(Mandatory = $true)] [string] $InputPath,
    [Parameter(Mandatory = $true)] [string] $Worker,
    [Parameter(Mandatory = $true)] [string] $CommunityRuntime,
    [Parameter(Mandatory = $true)] [string] $OfficialRuntimeDir,
    [string] $OutputDirectory = 'runtime/phase4a_soak',
    [string] $JobName = 'soak',
    [string] $PythonExecutable = 'C:\Users\mark\miniconda3\python.exe',
    [string] $FfprobeExecutable = '',
    [ValidateSet('h264_nvenc', 'libx264')] [string] $Codec = 'h264_nvenc',
    [ValidateSet(2, 3, 4)] [int] $Multiplier = 4,
    [int] $PerJobTimeoutSeconds = 2400,
    [int] $HeartbeatSeconds = 15,
    [switch] $RerunCompleted
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$out = Join-Path $root $OutputDirectory
New-Item -ItemType Directory -Force -Path $out | Out-Null
$jsonPath = Join-Path $out "$JobName.json"
$outputPath = Join-Path $out "$JobName.mp4"
$stdoutPath = Join-Path $out "$JobName.stdout.log"
$stderrPath = Join-Path $out "$JobName.stderr.log"

function Resolve-RequiredFile([string] $path, [string] $label) {
    $resolved = (Resolve-Path -LiteralPath $path -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw "$label is not a file: $resolved" }
    return $resolved
}
function Resolve-RequiredDirectory([string] $path, [string] $label) {
    $resolved = (Resolve-Path -LiteralPath $path -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) { throw "$label is not a directory: $resolved" }
    return $resolved
}
function Get-FreeBytes([string] $path) {
    $drive = (Get-Item -LiteralPath $path).PSDrive
    return [int64]$drive.Free
}
function Get-TreePids([int] $rootPid) {
    try { $all = @(Get-CimInstance Win32_Process -ErrorAction Stop) } catch { return @($rootPid) }
    $ids = [System.Collections.Generic.List[int]]::new(); $ids.Add($rootPid)
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($item in $all) { if ($ids.Contains([int]$item.ParentProcessId) -and -not $ids.Contains([int]$item.ProcessId)) { $ids.Add([int]$item.ProcessId); $changed = $true } }
    }
    return $ids
}
function Get-TreeWorkingSet([int] $rootPid) {
    $total = [int64]0
    foreach ($childPid in (Get-TreePids $rootPid)) { $p = Get-Process -Id $childPid -ErrorAction SilentlyContinue; if ($p) { $total += [int64]$p.WorkingSet64 } }
    return $total
}
function Read-Record([string] $path) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try { $value = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json; if (($value.status -eq 'PASS' -or $value.status -eq 'FAIL') -and $value.job) { return $value } } catch {}
    return $null
}
function Read-Pass([string] $path) {
    $value = Read-Record $path
    if ($value -and $value.status -eq 'PASS') { return $value }
    return $null
}
function Write-Summary([string] $directory) {
    $summaryPath = Join-Path $directory 'soak-summary.json'
    $records = @(Get-ChildItem -LiteralPath $directory -Filter '*.json' | Where-Object Name -ne 'soak-summary.json' | ForEach-Object { Read-Record $_.FullName } | Where-Object { $_ })
    @{ status = if (($records | Where-Object status -ne 'PASS').Count -eq 0) { 'PASS' } else { 'FAIL' }; generated_at = (Get-Date).ToUniversalTime().ToString('o'); jobs = $records } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding utf8
    $md = @('# Phase 4A soak summary', '', "Generated: $((Get-Date).ToUniversalTime().ToString('o'))", '', '| Job | Status | Wall (s) | Output bytes | Peak tree working set (MiB) |', '|---|---|---:|---:|---:|')
    foreach ($item in $records) { $md += "| $($item.job) | $($item.status) | $([math]::Round($item.wall_seconds, 2)) | $($item.output_bytes) | $([math]::Round($item.peak_tree_working_set_bytes / 1MB, 1)) |" }
    $md -join "`r`n" | Set-Content -LiteralPath (Join-Path $directory 'soak-summary.md') -Encoding utf8
}
function Stop-ProcessTree([int] $rootPid) {
    & taskkill.exe /PID $rootPid /T /F | Out-Host
    Start-Sleep -Milliseconds 500
    $root = Get-Process -Id $rootPid -ErrorAction SilentlyContinue
    if ($root) { Stop-Process -Id $rootPid -Force -ErrorAction SilentlyContinue }
    foreach ($candidate in @(Get-Process -Name python,ffmpeg,dlssg_sm86_offline,cmd,powershell -ErrorAction SilentlyContinue)) {
        if (-not $script:baselineProcessPids.Contains([int]$candidate.Id) -and [int]$candidate.Id -ne $rootPid) { Stop-Process -Id $candidate.Id -Force -ErrorAction SilentlyContinue }
    }
}
function Get-MemorySample([int] $rootPid) {
    $sample = [ordered]@{ elapsed_seconds = ((Get-Date) - $started).TotalSeconds; root_working_set_bytes = 0; python_working_set_bytes = 0; ffmpeg_working_set_bytes = 0; worker_working_set_bytes = 0; gpu_memory_used_mib = $null }
    $root = Get-Process -Id $rootPid -ErrorAction SilentlyContinue
    if ($root) { $sample.root_working_set_bytes = [int64]$root.WorkingSet64 }
    foreach ($candidate in @(Get-Process -Name ffmpeg,dlssg_sm86_offline -ErrorAction SilentlyContinue)) {
        $key = if ($candidate.ProcessName -eq 'ffmpeg') { 'ffmpeg_working_set_bytes' } else { 'worker_working_set_bytes' }
        $sample[$key] = [int64]$sample[$key] + [int64]$candidate.WorkingSet64
    }
    $sample.python_working_set_bytes = $sample.root_working_set_bytes
    $smi = 'C:\Windows\System32\nvidia-smi.exe'
    if (Test-Path -LiteralPath $smi) {
        try { $raw = & $smi '--query-gpu=memory.used' '--format=csv,noheader,nounits' 2>$null | Select-Object -First 1; if ($raw -match '^\s*(\d+)') { $sample.gpu_memory_used_mib = [int]$matches[1] } } catch {}
    }
    return [pscustomobject]$sample
}
function Write-Failure([string] $reason, [int] $exitCode) {
    $record = [ordered]@{ status = 'FAIL'; job = $JobName; started = $started.ToUniversalTime().ToString('o'); finished = (Get-Date).ToUniversalTime().ToString('o'); wall_seconds = ((Get-Date) - $started).TotalSeconds; exit_code = $exitCode; reason = $reason; input = $inputPath; input_sha256 = $inputHash; worker_sha256 = $workerHash; community_sha256 = $communityHash; output = $outputPath; stdout = $stdoutPath; stderr = $stderrPath; output_exists = (Test-Path -LiteralPath $outputPath) }
    $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $jsonPath -Encoding utf8
    Write-Summary $out
    throw $reason
}

$inputPath = Resolve-RequiredFile $InputPath 'input'
$workerPath = Resolve-RequiredFile $Worker 'worker'
$communityPath = Resolve-RequiredFile $CommunityRuntime 'community runtime'
$officialPath = Resolve-RequiredDirectory $OfficialRuntimeDir 'official runtime directory'
if (-not $FfprobeExecutable) { $FfprobeExecutable = (Get-Command ffprobe -ErrorAction SilentlyContinue).Source }
if (-not $FfprobeExecutable) { throw 'ffprobe is required; pass -FfprobeExecutable' }
$ffprobePath = Resolve-RequiredFile $FfprobeExecutable 'ffprobe'
$inputHash = (Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash
$workerHash = (Get-FileHash -LiteralPath $workerPath -Algorithm SHA256).Hash
$communityHash = (Get-FileHash -LiteralPath $communityPath -Algorithm SHA256).Hash
$beforeFree = Get-FreeBytes $out

$existing = if (-not $RerunCompleted) { Read-Pass $jsonPath } else { $null }
if ($existing) { Write-Host "[$(Get-Date -Format HH:mm:ss)] SKIP $JobName (existing PASS artifact)"; Write-Summary $out; exit 0 }

$args = @('tools/dlssg_video.py', '--input', $inputPath, '--output', $outputPath,
    '--worker', $workerPath, '--community-runtime', $communityPath, '--official-runtime-dir', $officialPath,
    '--codec', $Codec, '--multiplier', $Multiplier, '--terminal-frame-policy', 'duplicate')
$started = Get-Date
$script:baselineProcessPids = [System.Collections.Generic.HashSet[int]]::new()
foreach ($existingProcess in @(Get-Process -Name python,ffmpeg,dlssg_sm86_offline,cmd,powershell -ErrorAction SilentlyContinue)) { [void]$script:baselineProcessPids.Add([int]$existingProcess.Id) }
$proc = Start-Process -FilePath $PythonExecutable -ArgumentList $args -WorkingDirectory $root -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru -WindowStyle Hidden
Write-Host "[$(Get-Date -Format HH:mm:ss)] START $JobName pid=$($proc.Id) timeout=${PerJobTimeoutSeconds}s"
$peakWorkingSet = [int64]0; $lastHeartbeat = $started; $lastSample = $started; $memorySamples = @()
while (-not $proc.HasExited) {
    $now = Get-Date; $elapsed = ($now - $started).TotalSeconds
    $workingSet = Get-TreeWorkingSet $proc.Id; if ($workingSet -gt $peakWorkingSet) { $peakWorkingSet = $workingSet }
    if (($now - $lastSample).TotalSeconds -ge $HeartbeatSeconds) { $memorySamples += Get-MemorySample $proc.Id; $lastSample = $now }
    if (($now - $lastHeartbeat).TotalSeconds -ge $HeartbeatSeconds) { Write-Host "[$(Get-Date -Format HH:mm:ss)] HEARTBEAT $JobName elapsed=$([int]$elapsed)s workingSetMiB=$([math]::Round($workingSet / 1MB, 1))"; $lastHeartbeat = $now }
    if ($elapsed -ge $PerJobTimeoutSeconds) { $reason = "Job '$JobName' exceeded timeout"; Write-Warning "[$(Get-Date -Format HH:mm:ss)] TIMEOUT $JobName; terminating process tree"; Stop-ProcessTree $proc.Id; Write-Failure $reason -1 }
    Start-Sleep -Milliseconds 500; $proc.Refresh()
}
$proc.WaitForExit()
$afterFree = Get-FreeBytes $out
$stdout = Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue
$result = $null; try { $result = $stdout | ConvertFrom-Json } catch {}
if ($proc.ExitCode -ne 0 -or -not $result) { Write-Failure "Job '$JobName' failed with exit code $($proc.ExitCode); preserve $stdoutPath and $stderrPath" $proc.ExitCode }
$probe = & $ffprobePath -v error -show_format -show_streams -of json $outputPath 2>$null | ConvertFrom-Json
$record = [ordered]@{ status = 'PASS'; job = $JobName; started = $started.ToUniversalTime().ToString('o'); finished = (Get-Date).ToUniversalTime().ToString('o'); wall_seconds = ((Get-Date) - $started).TotalSeconds; exit_code = $proc.ExitCode; input = $inputPath; input_sha256 = $inputHash; worker_sha256 = $workerHash; community_sha256 = $communityHash; output = $outputPath; output_bytes = (Get-Item -LiteralPath $outputPath).Length; free_bytes_before = $beforeFree; free_bytes_after = $afterFree; peak_tree_working_set_bytes = $peakWorkingSet; memory_samples = $memorySamples; worker_exit_code = $result.lifecycle.worker_exit_code; encoder_exit_code = $result.lifecycle.encoder_exit_code; decoder_exit_code = $result.lifecycle.decoder_exit_code; result = $result; ffprobe = $probe }
$record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $jsonPath -Encoding utf8

Write-Summary $out
Write-Host "[$(Get-Date -Format HH:mm:ss)] PASS $JobName wall=$([math]::Round($record.wall_seconds, 2))s"
