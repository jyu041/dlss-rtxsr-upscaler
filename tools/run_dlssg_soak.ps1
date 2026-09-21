param(
    [Parameter(Mandatory = $true)] [string] $InputPath,
    [Parameter(Mandatory = $true)] [string] $Worker,
    [Parameter(Mandatory = $true)] [string] $CommunityRuntime,
    [Parameter(Mandatory = $true)] [string] $OfficialRuntimeDir,
    [string] $OutputDirectory = 'runtime/phase4a_soak',
    [string] $JobName = 'soak',
    [string] $PythonExecutable = '',
    [string] $FfprobeExecutable = '',
    [ValidateSet('h264_nvenc', 'libx264')] [string] $Codec = 'h264_nvenc',
    [ValidateSet(2, 3, 4)] [int] $Multiplier = 4,
    [int] $PerJobTimeoutSeconds = 2400,
    [int] $HeartbeatSeconds = 15,
    [switch] $RerunCompleted
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $PythonExecutable) { $PythonExecutable = (Get-Command python -ErrorAction Stop).Source }
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
    Update-SupervisedProcessTree
    return @($script:supervisedIdentities.Keys | ForEach-Object { [int]$_ })
}
function Get-ProcessIdentity([int] $processId) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    try {
        return [pscustomobject]@{ pid = [int]$process.Id; process_name = [string]$process.ProcessName; creation_time_ticks = [int64]$process.StartTime.ToUniversalTime().Ticks }
    } catch { return $null }
}
function Test-ProcessIdentity($identity) {
    $current = Get-ProcessIdentity ([int]$identity.pid)
    return ($current -and [int64]$current.creation_time_ticks -eq [int64]$identity.creation_time_ticks)
}
function Update-SupervisedProcessTree {
    try { $all = @(Get-CimInstance Win32_Process -ErrorAction Stop) } catch { return }
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($item in $all) {
            $parentPid = [int]$item.ParentProcessId
            if ($script:supervisedIdentities.ContainsKey($parentPid) -and (Test-ProcessIdentity $script:supervisedIdentities[$parentPid]) -and -not $script:supervisedIdentities.ContainsKey([int]$item.ProcessId)) {
                $identity = Get-ProcessIdentity ([int]$item.ProcessId)
                if ($identity) { $script:supervisedIdentities[[int]$item.ProcessId] = $identity; $changed = $true }
            }
        }
    }
}
function Get-TreeWorkingSet([int] $rootPid) {
    $total = [int64]0
    foreach ($childPid in (Get-TreePids $rootPid)) { $identity = $script:supervisedIdentities[[int]$childPid]; if ($identity -and (Test-ProcessIdentity $identity)) { $p = Get-Process -Id $childPid -ErrorAction SilentlyContinue; if ($p) { $total += [int64]$p.WorkingSet64 } } }
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
    Update-SupervisedProcessTree
    & taskkill.exe /PID $rootPid /T /F | Out-Host
    Start-Sleep -Milliseconds 500
    Update-SupervisedProcessTree
    foreach ($identity in @($script:supervisedIdentities.Values)) {
        if (Test-ProcessIdentity $identity) {
            Stop-Process -Id ([int]$identity.pid) -Force -ErrorAction SilentlyContinue
        }
    }
}
function Get-MemorySample([int] $rootPid) {
    Update-SupervisedProcessTree
    $sample = [ordered]@{ elapsed_seconds = ((Get-Date) - $started).TotalSeconds; root_working_set_bytes = 0; root_python_working_set_bytes = 0; python_working_set_bytes = 0; ffmpeg_working_set_bytes = 0; worker_working_set_bytes = 0; other_supervised_working_set_bytes = 0; total_tree_working_set_bytes = 0; tracked_processes = @(); gpu_memory_used_mib = $null }
    foreach ($identity in @($script:supervisedIdentities.Values)) {
        if (-not (Test-ProcessIdentity $identity)) { continue }
        $process = Get-Process -Id ([int]$identity.pid) -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        $bytes = [int64]$process.WorkingSet64
        $sample.tracked_processes += [pscustomobject]@{ pid = [int]$identity.pid; process_name = [string]$identity.process_name; creation_time_ticks = [int64]$identity.creation_time_ticks; working_set_bytes = $bytes }
        $sample.total_tree_working_set_bytes = [int64]$sample.total_tree_working_set_bytes + $bytes
        $name = ([string]$identity.process_name).ToLowerInvariant()
        if ([int]$identity.pid -eq $rootPid) { $sample.root_working_set_bytes = $bytes; if ($name -eq 'python') { $sample.root_python_working_set_bytes = $bytes } }
        elseif ($name -like 'ffmpeg*') { $sample.ffmpeg_working_set_bytes = [int64]$sample.ffmpeg_working_set_bytes + $bytes }
        elseif ($name -eq 'dlssg_sm86_offline') { $sample.worker_working_set_bytes = [int64]$sample.worker_working_set_bytes + $bytes }
        else { $sample.other_supervised_working_set_bytes = [int64]$sample.other_supervised_working_set_bytes + $bytes }
    }
    $sample.python_working_set_bytes = $sample.root_python_working_set_bytes
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
$proc = Start-Process -FilePath $PythonExecutable -ArgumentList $args -WorkingDirectory $root -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru -WindowStyle Hidden
$script:supervisedIdentities = @{}
$rootIdentity = Get-ProcessIdentity ([int]$proc.Id)
if ($rootIdentity) { $script:supervisedIdentities[[int]$proc.Id] = $rootIdentity }
Write-Host "[$(Get-Date -Format HH:mm:ss)] START $JobName pid=$($proc.Id) timeout=${PerJobTimeoutSeconds}s"
$peakWorkingSet = [int64]0; $lastHeartbeat = $started; $lastSample = $started; $memorySamples = @()
while (-not $proc.HasExited) {
    $now = Get-Date; $elapsed = ($now - $started).TotalSeconds
    Update-SupervisedProcessTree
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
