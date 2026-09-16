@echo off
setlocal
cd /d "%~dp0"
where powershell >nul 2>nul || (echo Windows PowerShell is required.& exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\repair_portable.ps1" -Root "%~dp0."
exit /b %errorlevel%
