@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
if not defined NVE_CONDA_ENV set "NVE_CONDA_ENV=dlss-rtxsr-upscaler"
if defined NVE_CONDA_PREFIX (set NVE_CONDA_TARGET=--prefix "%NVE_CONDA_PREFIX%") else (set NVE_CONDA_TARGET=--name "%NVE_CONDA_ENV%")
if defined NVE_CONDA_PREFIX (if not exist "%NVE_CONDA_PREFIX%\conda-meta\history" (echo NVE_CONDA_PREFIX must point to an existing Conda environment.& exit /b 2)) else (echo(%NVE_CONDA_ENV%| %SystemRoot%\System32\findstr.exe /r /x "[A-Za-z0-9][A-Za-z0-9_.-]*" >nul || (echo NVE_CONDA_ENV must contain only letters, numbers, underscore, period, or hyphen.& exit /b 2))
where conda >nul 2>nul || (echo Miniconda or Anaconda is required.& exit /b 1)
echo [1/5] Checking Conda
echo [2/5] Creating/updating Python environment
call conda env update %NVE_CONDA_TARGET% -f environment.yml --prune || exit /b 1
echo [3/5] Checking Python packages
call conda run --no-capture-output %NVE_CONDA_TARGET% python -m pip check || exit /b 1
echo [4/5] Checking FFmpeg/NVENC
set "NVE_FFMPEG=%~dp0runtime\tools\ffmpeg\ffmpeg.exe"
if not exist "%NVE_FFMPEG%" set "NVE_FFMPEG=ffmpeg"
set "NVE_FFPROBE=%~dp0runtime\tools\ffmpeg\ffprobe.exe"
if not exist "%NVE_FFPROBE%" set "NVE_FFPROBE=ffprobe"
"%NVE_FFMPEG%" -version >nul 2>nul || (echo FFmpeg was not found in runtime\tools\ffmpeg or on PATH. Install a compatible build or provide the bundled runtime.& exit /b 1)
"%NVE_FFPROBE%" -version >nul 2>nul || (echo FFprobe was not found in runtime\tools\ffmpeg or on PATH. Install a compatible build or provide the bundled runtime.& exit /b 1)
"%NVE_FFMPEG%" -hide_banner -encoders 2>nul | findstr /r /c:"h264_nvenc" /c:"hevc_nvenc" >nul || (echo FFmpeg lacks h264_nvenc/hevc_nvenc. Provide a full compatible build.& exit /b 1)
echo [5/5] Running diagnostics
call conda run --no-capture-output %NVE_CONDA_TARGET% python -m src.core.diagnostics || exit /b 1
if not exist config mkdir config
>"config\source_env.bat" echo @echo off
if defined NVE_CONDA_PREFIX (>>"config\source_env.bat" echo set "NVE_CONDA_PREFIX=%NVE_CONDA_PREFIX%") else (>>"config\source_env.bat" echo set "NVE_CONDA_ENV=%NVE_CONDA_ENV%")
echo Environment ready: %NVE_CONDA_ENV%
