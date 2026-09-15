@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
if not defined NVE_CONDA_ENV set "NVE_CONDA_ENV=dlss-rtxsr-upscaler"
if defined NVE_CONDA_PREFIX (set "NVE_CONDA_TARGET=--prefix \"%NVE_CONDA_PREFIX%\"") else (echo(%NVE_CONDA_ENV%| %SystemRoot%\System32\findstr.exe /r /x "[A-Za-z0-9][A-Za-z0-9_.-]*" >nul || (echo NVE_CONDA_ENV must contain only letters, numbers, underscore, period, or hyphen.& exit /b 2))
where conda >nul 2>nul || (echo Conda was not found. Run setup.bat first.& exit /b 1)
where ffmpeg >nul 2>nul || (echo FFmpeg was not found on PATH. Restart this shell or run setup.bat.& exit /b 1)
where ffprobe >nul 2>nul || (echo FFprobe was not found on PATH. Restart this shell or run setup.bat.& exit /b 1)
if exist runtime.local.ps1 powershell -NoProfile -ExecutionPolicy Bypass -File runtime.local.ps1
call conda run --no-capture-output %NVE_CONDA_TARGET% python app.py
