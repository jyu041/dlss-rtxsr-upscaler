param(
    [Parameter(Mandatory = $true)] [string] $OldWorker,
    [Parameter(Mandatory = $true)] [string] $NewWorker,
    [Parameter(Mandatory = $true)] [string] $ShortInput,
    [Parameter(Mandatory = $true)] [string] $LongInput,
    [Parameter(Mandatory = $true)] [string] $CommunityRuntime,
    [Parameter(Mandatory = $true)] [string] $OfficialRuntimeDir,
    [string] $PythonExecutable = 'C:\Users\mark\miniconda3\python.exe',
    [string] $OutputDirectory = 'runtime',
    [int] $Repeats = 3,
    [int] $PerRunTimeoutSeconds = 180,
    [int] $HeartbeatSeconds = 15,
    [switch] $NoEncodeControl,
    [switch] $RerunCompleted
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outputRoot = Join-Path $root $OutputDirectory
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

function Read-PassJson([string] $path) {
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    try { return ((Get-Content -LiteralPath $path -Raw | ConvertFrom-Json).status -eq 'PASS') }
    catch { return $false }
}

function Invoke-BenchmarkRun([string] $name, [string] $worker, [string] $inputPath) {
    $jsonPath = Join-Path $outputRoot "$name.json"
    if (-not $RerunCompleted -and (Read-PassJson $jsonPath)) {
        Write-Host "[$(Get-Date -Format HH:mm:ss)] SKIP $name (existing PASS JSON)"
        return
    }

    $outputPath = Join-Path $outputRoot "$name.mp4"
    $stdoutPath = Join-Path $outputRoot "$name.stdout.tmp"
    $stderrPath = Join-Path $outputRoot "$name.stderr.tmp"
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    $arguments = @(
        'tools/dlssg_video.py', '--input', $inputPath, '--output', $outputPath,
        '--worker', $worker, '--community-runtime', $CommunityRuntime,
        '--official-runtime-dir', $OfficialRuntimeDir, '--codec', 'h264_nvenc',
        '--multiplier', '4', '--terminal-frame-policy', 'duplicate', '--quiet-worker-log'
    )
    if ($NoEncodeControl) { $arguments += '--no-encode-control' }
    $started = Get-Date
    $process = Start-Process -FilePath $PythonExecutable -ArgumentList $arguments -WorkingDirectory $root -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru -WindowStyle Hidden
    Write-Host "[$(Get-Date -Format HH:mm:ss)] START $name pid=$($process.Id) timeout=${PerRunTimeoutSeconds}s"
    $lastHeartbeat = $started
    while (-not $process.HasExited) {
        $elapsed = ((Get-Date) - $started).TotalSeconds
        if ($elapsed -ge $PerRunTimeoutSeconds) {
            Write-Warning "[$(Get-Date -Format HH:mm:ss)] TIMEOUT $name elapsed=$([int]$elapsed)s; terminating pid=$($process.Id) tree"
            & taskkill.exe /PID $process.Id /T /F | Out-Host
            throw "Benchmark run '$name' exceeded ${PerRunTimeoutSeconds}s"
        }
        if (((Get-Date) - $lastHeartbeat).TotalSeconds -ge $HeartbeatSeconds) {
            Write-Host "[$(Get-Date -Format HH:mm:ss)] HEARTBEAT $name elapsed=$([int]$elapsed)s"
            $lastHeartbeat = Get-Date
        }
        Start-Sleep -Milliseconds 500
        $process.Refresh()
    }
    $process.WaitForExit()
    $stdout = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -LiteralPath $stdoutPath -Raw } else { '' }
    if ($stdout) { Set-Content -LiteralPath $jsonPath -Value $stdout -Encoding utf8 }
    if ($process.ExitCode -ne 0 -or -not (Read-PassJson $jsonPath)) {
        throw "Benchmark run '$name' failed with exit code $($process.ExitCode); inspect $jsonPath and $stderrPath"
    }
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    Write-Host "[$(Get-Date -Format HH:mm:ss)] PASS $name elapsed=$([int]((Get-Date) - $started).TotalSeconds)s"
}

foreach ($size in @(@{ suffix = '60'; input = $ShortInput }, @{ suffix = '600'; input = $LongInput })) {
    for ($rep = 0; $rep -lt $Repeats; $rep++) {
        foreach ($kind in @('old', 'new')) {
            $worker = if ($kind -eq 'old') { $OldWorker } else { $NewWorker }
            $name = "$kind$($size.suffix)$([char]([int][char]'a' + $rep))"
            Invoke-BenchmarkRun $name $worker $size.input
        }
    }
}
Write-Host "[$(Get-Date -Format HH:mm:ss)] COMPLETE all requested runs"
