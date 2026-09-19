@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
if not exist "%~dp0runtime\python\python.exe" goto source_mode
if not exist "%~dp0runtime\tools\ffmpeg\ffmpeg.exe" (echo Portable FFmpeg is missing. Run repair.bat or build a complete candidate.& exit /b 1)
if not exist "%~dp0runtime\tools\ffmpeg\ffprobe.exe" (echo Portable FFprobe is missing. Run repair.bat or build a complete candidate.& exit /b 1)
set "NVE_FFMPEG_PATH=%~dp0runtime\tools\ffmpeg\ffmpeg.exe"
set "NVE_FFPROBE_PATH=%~dp0runtime\tools\ffmpeg\ffprobe.exe"
call "%~dp0runtime\python\python.exe" "%~dp0tools\check_portable_runtime.py" --root "%~dp0." || (echo Portable runtime requires repair. Run repair.bat.& exit /b 1)
call "%~dp0runtime\python\python.exe" "%~dp0app.py"
exit /b %errorlevel%

:source_mode
if exist "%~dp0config\source_env.bat" call "%~dp0config\source_env.bat"
if not defined NVE_CONDA_ENV if not defined NVE_CONDA_PREFIX set "NVE_CONDA_ENV=dlss-rtxsr-upscaler"
if defined NVE_CONDA_PREFIX (set NVE_CONDA_TARGET=--prefix "%NVE_CONDA_PREFIX%") else (set NVE_CONDA_TARGET=--name "%NVE_CONDA_ENV%")
if defined NVE_CONDA_EXE if not exist "%NVE_CONDA_EXE%" set "NVE_CONDA_EXE="
if not defined NVE_CONDA_EXE for /f "delims=" %%C in ('where conda 2^>nul') do if not defined NVE_CONDA_EXE set "NVE_CONDA_EXE=%%C"
if not defined NVE_CONDA_EXE for %%C in ("%USERPROFILE%\miniconda3\condabin\conda.bat" "%USERPROFILE%\miniconda3\Scripts\conda.exe" "%USERPROFILE%\anaconda3\condabin\conda.bat" "%USERPROFILE%\anaconda3\Scripts\conda.exe" "%LOCALAPPDATA%\miniconda3\condabin\conda.bat" "%LOCALAPPDATA%\anaconda3\condabin\conda.bat" "%ProgramData%\miniconda3\condabin\conda.bat" "%ProgramData%\anaconda3\condabin\conda.bat") do if not defined NVE_CONDA_EXE if exist "%%~C" set "NVE_CONDA_EXE=%%~C"
if not defined NVE_CONDA_EXE (echo Conda was not found. Run setup.bat after installing Miniconda or Anaconda.& exit /b 1)
set "NVE_FFMPEG_PATH=%~dp0runtime\tools\ffmpeg\ffmpeg.exe"
if not exist "%NVE_FFMPEG_PATH%" set "NVE_FFMPEG_PATH="
set "NVE_FFPROBE_PATH=%~dp0runtime\tools\ffmpeg\ffprobe.exe"
if not exist "%NVE_FFPROBE_PATH%" set "NVE_FFPROBE_PATH="
if not defined NVE_FFMPEG_PATH (where ffmpeg >nul 2>nul || (echo FFmpeg was not found in runtime\tools\ffmpeg or on PATH. Run setup.bat after installing a compatible build.& exit /b 1))
if not defined NVE_FFPROBE_PATH (where ffprobe >nul 2>nul || (echo FFprobe was not found in runtime\tools\ffmpeg or on PATH. Run setup.bat after installing a compatible build.& exit /b 1))
echo Starting source environment...
call "%NVE_CONDA_EXE%" run --no-capture-output %NVE_CONDA_TARGET% python "%~dp0app.py"
exit /b %errorlevel%
