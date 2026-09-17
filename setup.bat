@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
if not defined NVE_CONDA_ENV set "NVE_CONDA_ENV=dlss-rtxsr-upscaler"
if defined NVE_CONDA_PREFIX (set NVE_CONDA_TARGET=--prefix "%NVE_CONDA_PREFIX%") else (set NVE_CONDA_TARGET=--name "%NVE_CONDA_ENV%")
if defined NVE_CONDA_PREFIX (if not exist "%NVE_CONDA_PREFIX%\conda-meta\history" (echo NVE_CONDA_PREFIX must point to an existing Conda environment.& exit /b 2)) else (echo(%NVE_CONDA_ENV%| %SystemRoot%\System32\findstr.exe /r /x "[A-Za-z0-9][A-Za-z0-9_.-]*" >nul || (echo NVE_CONDA_ENV must contain only letters, numbers, underscore, period, or hyphen.& exit /b 2))
where conda >nul 2>nul || (echo Miniconda or Anaconda is required.& exit /b 1)

echo [1/10] Checking Conda
echo [2/10] Creating/updating Python environment
call conda env update %NVE_CONDA_TARGET% -f environment.yml --prune || exit /b 1

echo [3/10] Checking Python packages
call conda run --no-capture-output %NVE_CONDA_TARGET% python -m pip check || exit /b 1

echo [4/10] Checking FFmpeg/NVENC
set "NVE_FFMPEG=%~dp0runtime\tools\ffmpeg\ffmpeg.exe"
if not exist "%NVE_FFMPEG%" set "NVE_FFMPEG=ffmpeg"
set "NVE_FFPROBE=%~dp0runtime\tools\ffmpeg\ffprobe.exe"
if not exist "%NVE_FFPROBE%" set "NVE_FFPROBE=ffprobe"
"%NVE_FFMPEG%" -version >nul 2>nul || (echo FFmpeg was not found in runtime\tools\ffmpeg or on PATH. Install a compatible build or provide the bundled runtime.& exit /b 1)
"%NVE_FFPROBE%" -version >nul 2>nul || (echo FFprobe was not found in runtime\tools\ffmpeg or on PATH. Install a compatible build or provide the bundled runtime.& exit /b 1)
"%NVE_FFMPEG%" -hide_banner -encoders 2>nul | findstr /r /c:"h264_nvenc" /c:"hevc_nvenc" >nul || (echo FFmpeg lacks h264_nvenc/hevc_nvenc. Provide a full compatible build.& exit /b 1)

echo [5/10] Installing project-owned public runtimes
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

echo [6/10] Installing DLSS-G runtimes from upstream
set "DLSSG_RUNTIME_PROFILE=legacy"
set "DLSSG_COMMUNITY_RUNTIME=%~dp0runtime\dlssg\legacy\version.dll"
set "DLSSG_OFFICIAL_RUNTIME_DIR=%~dp0runtime\dlssg\official"
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py verify dlssg-legacy-reference >nul 2>nul
if errorlevel 1 (
  echo Downloading the validated SM86 legacy runtime directly from its upstream GitHub commit...
  call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py install dlssg-legacy-reference
  if errorlevel 1 echo WARNING: DLSS-G community runtime setup failed. Other backends can still be used; rerun setup.bat later.
)
set "NVE_STREAMLINE_ARCHIVE=%TEMP%\streamline-sdk-v2.14.1-nve.zip"
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py verify dlssg-official-provider-310.9.1 >nul 2>nul
if errorlevel 1 (
  echo Downloading the pinned NVIDIA Streamline DLSS-G provider from NVIDIA's GitHub release...
  call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py install dlssg-official-provider-310.9.1 --archive-target "%NVE_STREAMLINE_ARCHIVE%"
  if errorlevel 1 echo WARNING: NVIDIA DLSS-G provider setup failed. Other backends can still be used; rerun setup.bat later.
)
del /q "%NVE_STREAMLINE_ARCHIVE%" >nul 2>nul

echo [7/10] Installing DLSS 5 runtime from upstream
set "DLSS5_RUNTIME_DIR=%~dp0runtime\dlss5-v3"
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\bootstrap_dlss5_runtime.py --check >nul 2>nul
if errorlevel 1 (
  echo Downloading DLSS 5 Visual Enhancer v3.0 runtime directly from its upstream GitHub release...
  call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\bootstrap_dlss5_runtime.py
  if errorlevel 1 echo WARNING: DLSS 5 runtime setup failed. Other backends can still be used; rerun setup.bat later.
)

echo [8/10] Running automatic backend self-tests
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\check_dlss_sr_readiness.py --selftest
if errorlevel 1 echo WARNING: DLSS SR self-test did not pass on this machine. Setup will continue.
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\bootstrap_dlss5_runtime.py --check >nul 2>nul
if not errorlevel 1 (
  call conda run --no-capture-output %NVE_CONDA_TARGET% python -m src.backends.dlss5_selftest
  if errorlevel 1 echo WARNING: DLSS 5 Feature-18 self-test did not pass on this GPU/runtime. Setup will continue.
)

echo [9/10] Running diagnostics
call conda run --no-capture-output %NVE_CONDA_TARGET% python -m src.core.diagnostics || exit /b 1

echo [10/10] Saving source environment
if not exist config mkdir config
>"config\source_env.bat" echo @echo off
if defined NVE_CONDA_PREFIX (>>"config\source_env.bat" echo set "NVE_CONDA_PREFIX=%NVE_CONDA_PREFIX%") else (>>"config\source_env.bat" echo set "NVE_CONDA_ENV=%NVE_CONDA_ENV%")
>>"config\source_env.bat" echo set "DLSSG_WORKER_EXE=%%~dp0..\runtime\dlssg\worker\dlssg_sm86_offline.exe"
>>"config\source_env.bat" echo set "DLSSG_RUNTIME_PROFILE=legacy"
>>"config\source_env.bat" echo set "DLSSG_COMMUNITY_RUNTIME=%%~dp0..\runtime\dlssg\legacy\version.dll"
>>"config\source_env.bat" echo set "DLSSG_OFFICIAL_RUNTIME_DIR=%%~dp0..\runtime\dlssg\official"
>>"config\source_env.bat" echo set "DLSS5_RUNTIME_DIR=%%~dp0..\runtime\dlss5-v3"

echo Environment ready: %NVE_CONDA_ENV%
echo Setup automatically installed every runtime that can be fetched directly from a pinned public upstream source.
echo If a backend self-test is unsupported on this GPU or an upstream download failed, the application will report that backend as unavailable without blocking the others.
