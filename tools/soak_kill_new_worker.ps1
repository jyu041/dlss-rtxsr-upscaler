param(
    [string] $PidFile,
    [int] $DelaySeconds = 3
)

Start-Sleep -Seconds $DelaySeconds
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $worker = Get-Process -Name dlssg_sm86_offline -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($worker) {
        $worker.Id | Set-Content -LiteralPath $PidFile -Encoding ascii
        Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue
        exit 0
    }
    Start-Sleep -Milliseconds 250
}
exit 2
