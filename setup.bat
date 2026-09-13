@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
where conda >nul 2>nul || (echo Miniconda or Anaconda is required.& exit /b 1)
conda env update -n dlss-rtxsr-upscaler -f environment.yml --prune || exit /b 1
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pip check
where ffmpeg >nul 2>nul || (echo FFmpeg was not found on PATH. Install Gyan.FFmpeg with: winget install --id Gyan.FFmpeg --source winget.& exit /b 1)
where ffprobe >nul 2>nul || (echo FFprobe was not found on PATH. Install Gyan.FFmpeg with winget.& exit /b 1)
ffmpeg -version >nul 2>nul || (echo FFmpeg cannot launch. Restart the shell after installing Gyan.FFmpeg and rerun setup.bat.& exit /b 1)
ffprobe -version >nul 2>nul || (echo FFprobe cannot launch. Restart the shell after installing Gyan.FFmpeg and rerun setup.bat.& exit /b 1)
ffmpeg -hide_banner -encoders 2>nul | findstr /r /c:"h264_nvenc" /c:"hevc_nvenc" >nul || (echo FFmpeg lacks h264_nvenc/hevc_nvenc. Install Gyan.FFmpeg full build with winget.& exit /b 1)
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m src.core.diagnostics
echo Environment ready: dlss-rtxsr-upscaler
