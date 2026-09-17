@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
if not defined NVE_CONDA_ENV set "NVE_CONDA_ENV=dlss-rtxsr-upscaler"
if defined NVE_CONDA_PREFIX (set NVE_CONDA_TARGET=--prefix "%NVE_CONDA_PREFIX%") else (set NVE_CONDA_TARGET=--name "%NVE_CONDA_ENV%")
if defined NVE_CONDA_PREFIX (if not exist "%NVE_CONDA_PREFIX%\conda-meta\history" (echo NVE_CONDA_PREFIX must point to an existing Conda environment.& exit /b 2)) else (echo(%NVE_CONDA_ENV%| %SystemRoot%\System32\findstr.exe /r /x "[A-Za-z0-9][A-Za-z0-9_.-]*" >nul || (echo NVE_CONDA_ENV must contain only letters, numbers, underscore, period, or hyphen.& exit /b 2))
where conda >nul 2>nul || (echo Miniconda or Anaconda is required.& exit /b 1)
echo [1/7] Checking Conda
echo [2/7] Creating/updating Python environment
call conda env update %NVE_CONDA_TARGET% -f environment.yml --prune || exit /b 1
echo [3/7] Checking Python packages
call conda run --no-capture-output %NVE_CONDA_TARGET% python -m pip check || exit /b 1
echo [4/7] Checking FFmpeg/NVENC
set "NVE_FFMPEG=%~dp0runtime\tools\ffmpeg\ffmpeg.exe"
if not exist "%NVE_FFMPEG%" set "NVE_FFMPEG=ffmpeg"
set "NVE_FFPROBE=%~dp0runtime\tools\ffmpeg\ffprobe.exe"
if not exist "%NVE_FFPROBE%" set "NVE_FFPROBE=ffprobe"
"%NVE_FFMPEG%" -version >nul 2>nul || (echo FFmpeg was not found in runtime\tools\ffmpeg or on PATH. Install a compatible build or provide the bundled runtime.& exit /b 1)
"%NVE_FFPROBE%" -version >nul 2>nul || (echo FFprobe was not found in runtime\tools\ffmpeg or on PATH. Install a compatible build or provide the bundled runtime.& exit /b 1)
"%NVE_FFMPEG%" -hide_banner -encoders 2>nul | findstr /r /c:"h264_nvenc" /c:"hevc_nvenc" >nul || (echo FFmpeg lacks h264_nvenc/hevc_nvenc. Provide a full compatible build.& exit /b 1)
echo [5/7] Installing verified public project runtimes
set "NVE_BOOTSTRAP_ARCHIVE=%TEMP%\NVIDIA-Video-Enhancer-v0.1.0-beta.2-bootstrap.zip"
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py verify project-c55-worker-beta2 >nul 2>nul
if errorlevel 1 (
  echo Installing validated C55 DLSS-G worker from the public v0.1.0-beta.2 release...
  call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py install project-c55-worker-beta2 --archive-target "%NVE_BOOTSTRAP_ARCHIVE%" || exit /b 1
)
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py verify project-dlss-sr-beta2 >nul 2>nul
if errorlevel 1 (
  echo Installing validated DLSS SR host/runtime from the public v0.1.0-beta.2 release...
  call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py install project-dlss-sr-beta2 --archive-target "%NVE_BOOTSTRAP_ARCHIVE%" || exit /b 1
)
del /q "%NVE_BOOTSTRAP_ARCHIVE%" >nul 2>nul
set "DLSSG_WORKER_EXE=%~dp0runtime\dlssg\worker\dlssg_sm86_offline.exe"
if not exist "%DLSSG_WORKER_EXE%" (echo Validated C55 worker bootstrap did not produce the expected file.& exit /b 1)
if not exist "%~dp0runtime\dlss-sr-host\dlss_sr_host.exe" (echo DLSS SR host bootstrap did not produce the expected file.& exit /b 1)
if not exist "%~dp0runtime\dlss-sr-host\nvngx_dlss.dll" (echo DLSS SR runtime bootstrap did not produce the expected file.& exit /b 1)
if not exist "%~dp0native\dlssg_sm86_offline\bin" mkdir "%~dp0native\dlssg_sm86_offline\bin" || exit /b 1
copy /y "%DLSSG_WORKER_EXE%" "%~dp0native\dlssg_sm86_offline\bin\dlssg_sm86_offline.exe" >nul || exit /b 1
echo [6/7] Running diagnostics
call conda run --no-capture-output %NVE_CONDA_TARGET% python -m src.core.diagnostics || exit /b 1
echo [7/7] Saving source environment
if not exist config mkdir config
>"config\source_env.bat" echo @echo off
if defined NVE_CONDA_PREFIX (>>"config\source_env.bat" echo set "NVE_CONDA_PREFIX=%NVE_CONDA_PREFIX%") else (>>"config\source_env.bat" echo set "NVE_CONDA_ENV=%NVE_CONDA_ENV%")
>>"config\source_env.bat" echo set "DLSSG_WORKER_EXE=%%~dp0..\runtime\dlssg\worker\dlssg_sm86_offline.exe"
echo Environment ready: %NVE_CONDA_ENV%
echo Project-owned C55 and DLSS SR runtime resources are installed from the public GitHub release.
echo Optional DLSS-G community/official runtimes and DLSS 5 runtimes remain explicit Runtime Manager or user-supplied components.
