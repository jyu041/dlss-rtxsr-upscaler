$grandchild = Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-Command', 'Start-Sleep -Seconds 120' -PassThru
if ($env:SOAK_FIXTURE_PID_FILE) {
    "$PID,$($grandchild.Id)" | Set-Content -LiteralPath $env:SOAK_FIXTURE_PID_FILE -Encoding ascii
}
Start-Sleep -Seconds 120
