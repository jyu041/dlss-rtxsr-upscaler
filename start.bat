@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
if not exist "%~dp0runtime\python\python.exe" (echo Portable Python is missing. Run repair.bat or build a complete candidate.& exit /b 1)
if not exist "%~dp0runtime\tools\ffmpeg\ffmpeg.exe" (echo Portable FFmpeg is missing. Run repair.bat or build a complete candidate.& exit /b 1)
if not exist "%~dp0runtime\tools\ffmpeg\ffprobe.exe" (echo Portable FFprobe is missing. Run repair.bat or build a complete candidate.& exit /b 1)
set "NVE_FFMPEG_PATH=%~dp0runtime\tools\ffmpeg\ffmpeg.exe"
set "NVE_FFPROBE_PATH=%~dp0runtime\tools\ffmpeg\ffprobe.exe"
call "%~dp0runtime\python\python.exe" "%~dp0tools\check_portable_runtime.py" --root "%~dp0" || (echo Portable runtime requires repair. Run repair.bat.& exit /b 1)
call "%~dp0runtime\python\python.exe" "%~dp0app.py"
exit /b %errorlevel%
