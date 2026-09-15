@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
if not defined NVE_CONDA_ENV set "NVE_CONDA_ENV=dlss-rtxsr-upscaler"
if defined NVE_CONDA_PREFIX (set "NVE_CONDA_TARGET=--prefix \"%NVE_CONDA_PREFIX%\"") else (set "NVE_CONDA_TARGET=--name \"%NVE_CONDA_ENV%\"")
if defined NVE_CONDA_PREFIX (if not exist "%NVE_CONDA_PREFIX%\conda-meta\history" (echo NVE_CONDA_PREFIX must point to an existing Conda environment.& exit /b 2)) else (echo(%NVE_CONDA_ENV%| %SystemRoot%\System32\findstr.exe /r /x "[A-Za-z0-9][A-Za-z0-9_.-]*" >nul || (echo NVE_CONDA_ENV must contain only letters, numbers, underscore, period, or hyphen.& exit /b 2))
where conda >nul 2>nul || (echo Miniconda or Anaconda is required.& exit /b 1)
echo [1/5] Checking Conda
echo [2/5] Creating/updating Python environment
call conda env update %NVE_CONDA_TARGET% -f environment.yml --prune || exit /b 1
echo [3/5] Checking Python packages
call conda run --no-capture-output %NVE_CONDA_TARGET% python -m pip check || exit /b 1
echo [4/5] Checking FFmpeg/NVENC
where ffmpeg >nul 2>nul || (echo FFmpeg was not found on PATH. Install Gyan.FFmpeg with: winget install --id Gyan.FFmpeg --source winget.& exit /b 1)
where ffprobe >nul 2>nul || (echo FFprobe was not found on PATH. Install Gyan.FFmpeg with winget.& exit /b 1)
ffmpeg -version >nul 2>nul || (echo FFmpeg cannot launch. Restart the shell after installing Gyan.FFmpeg and rerun setup.bat.& exit /b 1)
ffprobe -version >nul 2>nul || (echo FFprobe cannot launch. Restart the shell after installing Gyan.FFmpeg and rerun setup.bat.& exit /b 1)
ffmpeg -hide_banner -encoders 2>nul | findstr /r /c:"h264_nvenc" /c:"hevc_nvenc" >nul || (echo FFmpeg lacks h264_nvenc/hevc_nvenc. Install Gyan.FFmpeg full build with winget.& exit /b 1)
echo [5/5] Running diagnostics
call conda run --no-capture-output %NVE_CONDA_TARGET% python -m src.core.diagnostics || exit /b 1
echo Environment ready: %NVE_CONDA_ENV%
