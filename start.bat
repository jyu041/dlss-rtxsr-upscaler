@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
where conda >nul 2>nul || (echo Conda was not found. Run setup.bat first.& exit /b 1)
where ffmpeg >nul 2>nul || (echo FFmpeg was not found on PATH. Restart this shell or run setup.bat.& exit /b 1)
where ffprobe >nul 2>nul || (echo FFprobe was not found on PATH. Restart this shell or run setup.bat.& exit /b 1)
if exist runtime.local.ps1 powershell -NoProfile -ExecutionPolicy Bypass -File runtime.local.ps1
conda run --no-capture-output -n dlss-rtxsr-upscaler python app.py
