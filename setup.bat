@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
if not defined NVE_CONDA_ENV set "NVE_CONDA_ENV=dlss-rtxsr-upscaler"
if defined NVE_CONDA_PREFIX (set NVE_CONDA_TARGET=--prefix "%NVE_CONDA_PREFIX%") else (set NVE_CONDA_TARGET=--name "%NVE_CONDA_ENV%")
if defined NVE_CONDA_PREFIX (if not exist "%NVE_CONDA_PREFIX%\conda-meta\history" (echo NVE_CONDA_PREFIX must point to an existing Conda environment.& exit /b 2)) else (echo(%NVE_CONDA_ENV%| %SystemRoot%\System32\findstr.exe /r /x "[A-Za-z0-9][A-Za-z0-9_.-]*" >nul || (echo NVE_CONDA_ENV must contain only letters, numbers, underscore, period, or hyphen.& exit /b 2))
where conda >nul 2>nul || (echo Miniconda or Anaconda is required.& exit /b 1)

echo [1/10] Checking setup network/proxy and Conda
powershell.exe -NoProfile -NonInteractive -Command "$bad=@(); foreach($n in @('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')){$v=[Environment]::GetEnvironmentVariable($n); if(-not $v){continue}; $candidate=$v; if($candidate -notmatch '://'){$candidate='http://'+$candidate}; try{$u=[Uri]$candidate}catch{continue}; if(($u.Host -in @('127.0.0.1','localhost','::1')) -and $u.Port -eq 9){$bad += ($n+'='+$v)}}; if($bad.Count -gt 0){Write-Host ('NETWORK BLOCKED: setup inherited a local discard proxy: '+($bad -join ', ')); exit 2}"
if errorlevel 2 (
  echo This shell intentionally blocks child-process network access through 127.0.0.1:9.
  echo Run setup.bat from a normal network-enabled terminal. The project will not bypass a sandbox or automation security boundary.
  exit /b 2
)

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

echo [5/10] Installing verified public project runtimes
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

echo [6/10] Installing managed DLSS-G provider and compatibility runtime
set "NVE_DLSSG_PROVIDER_ARCHIVE=%TEMP%\NVIDIA-Streamline-v2.14.1.zip"
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py verify dlssg-official-provider-310.9.1 >nul 2>nul
if errorlevel 1 (
  echo Installing pinned NVIDIA DLSS-G provider from the public Streamline release...
  call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py install dlssg-official-provider-310.9.1 --archive-target "%NVE_DLSSG_PROVIDER_ARCHIVE%" || exit /b 1
)
del /q "%NVE_DLSSG_PROVIDER_ARCHIVE%" >nul 2>nul

call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py verify dlssg-sm86-0.3.1-candidate >nul 2>nul
if errorlevel 1 (
  echo Installing or repairing the pinned SM86 0.3.1 DLSS-G compatibility runtime from its public upstream source...
  call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\manage_runtime.py install dlssg-sm86-0.3.1-candidate || exit /b 1
)

set "DLSSG_RUNTIME_PROFILE=candidate-0.3.1"
set "DLSSG_COMMUNITY_RUNTIME=%~dp0runtime\dlssg\candidate-0.3.1\version.dll"
set "DLSSG_OFFICIAL_RUNTIME_DIR=%~dp0runtime\dlssg\official"
if not exist "%DLSSG_COMMUNITY_RUNTIME%" (echo Managed DLSS-G compatibility runtime was not installed correctly.& exit /b 1)
if not exist "%DLSSG_OFFICIAL_RUNTIME_DIR%\nvngx_dlssg.dll" (echo Managed NVIDIA DLSS-G provider was not installed correctly.& exit /b 1)

echo [7/10] Optional managed DLSS 5 v3 provisioning
set "NVE_DLSS5_CHOICE="
if /I "%NVE_SETUP_DLSS5%"=="1" set "NVE_DLSS5_CHOICE=Y"
if /I "%NVE_SETUP_DLSS5%"=="0" set "NVE_DLSS5_CHOICE=N"
if not defined NVE_DLSS5_CHOICE (
  echo DLSS 5 v3 is experimental and requires an explicit local approval, malware scan, firewall block, and hardware self-test.
  choice /C YN /N /M "Provision the pinned validated DLSS 5 v3 runtime now? [Y/N] "
  if errorlevel 2 (set "NVE_DLSS5_CHOICE=N") else (set "NVE_DLSS5_CHOICE=Y")
)
if /I "%NVE_DLSS5_CHOICE%"=="Y" (
  echo The DLSS 5 provisioner may show a Windows UAC prompt to create the exact outbound worker firewall rule.
  if defined NVE_DLSS5_ARCHIVE (
    echo Using the explicitly supplied DLSS 5 v3 archive: %NVE_DLSS5_ARCHIVE%
    call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\provision_dlss5_v3.py --yes --archive "%NVE_DLSS5_ARCHIVE%"
    if errorlevel 1 echo WARNING: DLSS 5 v3 provisioning or Feature-18 validation did not complete. Other backends remain usable; DLSS 5 stays unavailable until its gates pass.
  ) else (
    call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\check_setup_network.py --require-download
    if errorlevel 1 (
      echo WARNING: DLSS 5 v3 download was skipped because this shell has no usable setup download path. Other backends remain usable.
      echo Run setup.bat from a normal network-enabled shell and rerun setup.
    ) else (
      set "NVE_DLSS5_MANAGED_ARCHIVE=%~dp0runtime\cache\dlss5-v3\DLSS.5.Visual.Enhancer.v3.0.zip"
      call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\cache_dlss5_v3_archive.py
      if errorlevel 1 (
        echo WARNING: DLSS 5 v3 archive download/cache verification failed. Other backends remain usable.
      ) else (
        call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\provision_dlss5_v3.py --yes --archive "%NVE_DLSS5_MANAGED_ARCHIVE%"
        if errorlevel 1 echo WARNING: DLSS 5 v3 provisioning or Feature-18 validation did not complete. The verified archive remains cached for a later retry.
      )
    )
  )
) else (
  echo Skipping optional DLSS 5 v3 provisioning. You can run tools\provision_dlss5_v3.py later.
)

echo [8/10] Running backend validation
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\check_dlss_sr_readiness.py --selftest
if errorlevel 1 echo WARNING: DLSS SR self-test did not pass on this machine. The verified files remain installed and no manual path configuration is required.
call conda run --no-capture-output %NVE_CONDA_TARGET% python tools\validate_dlssg_candidate.py --official "%DLSSG_OFFICIAL_RUNTIME_DIR%"
if errorlevel 1 echo WARNING: DLSS-G compatibility validation did not pass on this machine. The managed files remain installed and no manual path configuration is required.

echo [9/10] Running diagnostics
call conda run --no-capture-output %NVE_CONDA_TARGET% python -m src.core.diagnostics || exit /b 1

echo [10/10] Saving source environment
if not exist config mkdir config
>"config\source_env.bat" echo @echo off
if defined NVE_CONDA_PREFIX (>>"config\source_env.bat" echo set "NVE_CONDA_PREFIX=%NVE_CONDA_PREFIX%") else (>>"config\source_env.bat" echo set "NVE_CONDA_ENV=%NVE_CONDA_ENV%")
>>"config\source_env.bat" echo set "DLSSG_WORKER_EXE=%%~dp0..\runtime\dlssg\worker\dlssg_sm86_offline.exe"
>>"config\source_env.bat" echo set "DLSSG_RUNTIME_PROFILE=candidate-0.3.1"
>>"config\source_env.bat" echo set "DLSSG_COMMUNITY_RUNTIME=%%~dp0..\runtime\dlssg\candidate-0.3.1\version.dll"
>>"config\source_env.bat" echo set "DLSSG_OFFICIAL_RUNTIME_DIR=%%~dp0..\runtime\dlssg\official"

echo.
echo Environment ready: %NVE_CONDA_ENV%
echo C55, DLSS SR, and the managed DLSS-G provider/runtime are installed from pinned public sources.
echo Normal use does not require downloading backend DLLs manually or entering runtime paths in the UI.
echo DLSS 5 v3 can also be provisioned from its pinned upstream release through the explicit setup opt-in; it remains experimental and fail-closed behind hash, scan, firewall, and Feature-18 self-test gates.
