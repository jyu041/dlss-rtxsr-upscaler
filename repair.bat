@echo off
setlocal
cd /d "%~dp0"

rem The supported product is the source/Conda install. A complete portable
rem runtime is repaired with the retained portable research path; otherwise
rem repair means re-running the idempotent source setup.
if exist "%~dp0runtime\python\python.exe" goto portable_repair

echo Repairing source installation through setup.bat...
call "%~dp0setup.bat"
exit /b %errorlevel%

:portable_repair
where powershell >nul 2>nul || (echo Windows PowerShell is required.& exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\repair_portable.ps1" -Root "%~dp0."
exit /b %errorlevel%
